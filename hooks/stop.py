#!/usr/bin/env python3
"""
Stop Hook - Session Summary Generator
Reads the transcript, extracts last assistant response, includes project context
(CLAUDE.md and PLAN.md), calls Claude Code CLI (haiku) to generate a summary, and saves to the project.
"""

import json
import re
import sys
import os
import subprocess
import pty
import select
import time
from datetime import datetime

# Use Claude Code CLI instead of local Ollama for better quality summaries
CLAUDE_MODEL = "haiku"  # Fast and cheap, good for summaries
DEBUG_LOG = "/tmp/claude-debug-stop.log"

def find_claude_cli() -> str:
    """Find the claude CLI binary, checking common locations."""
    import shutil
    # Check PATH first
    found = shutil.which("claude")
    if found:
        return found
    # Common install locations
    common_paths = [
        os.path.expanduser("~/.claude/local/claude"),
        os.path.expanduser("~/.local/bin/claude"),
        "/usr/local/bin/claude",
        os.path.expanduser("~/.npm-global/bin/claude"),
    ]
    for path in common_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return "claude"  # Fallback, hope it's in PATH

def debug_log(message):
    """Log debugging info with timestamp (only if CLAUDE_HOOK_DEBUG=1)"""
    if os.environ.get("CLAUDE_HOOK_DEBUG") != "1":
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    with open(DEBUG_LOG, "a") as f:
        f.write(f"[{timestamp}] {message}\n")
        f.flush()


def write_session_file(session_id: str, cwd: str, status: str, summary: str = None):
    """Write session state to ~/.claude/sessions/ for Whisper Village to read.

    Summary can be either:
    - A plain string (legacy format): "USER asked: ...\nAGENT: ..."
    - A JSON string: {"user_summary": "...", "agent_summary": "..."}
    """
    sessions_dir = os.path.expanduser("~/.claude/sessions")
    os.makedirs(sessions_dir, exist_ok=True)

    # Use a hash of cwd as filename to avoid path issues
    import hashlib
    cwd_hash = hashlib.md5(cwd.encode()).hexdigest()[:12]
    session_file = os.path.join(sessions_dir, f"{cwd_hash}.json")

    # Try to parse summary as JSON for structured format
    user_summary = None
    agent_summary = None
    if summary:
        # Strip markdown code fences if present
        clean_summary = summary.strip()
        if clean_summary.startswith("```"):
            # Remove opening fence (```json or ```)
            lines = clean_summary.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Remove closing fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean_summary = "\n".join(lines).strip()

        try:
            parsed = json.loads(clean_summary)
            if isinstance(parsed, dict):
                user_summary = parsed.get("user_summary")
                agent_summary = parsed.get("agent_summary")
                debug_log(f"Parsed structured summary: user={user_summary[:50] if user_summary else None}...")
        except json.JSONDecodeError:
            debug_log(f"JSON parse failed, trying legacy format")
            # Legacy format - try to extract from "USER asked: ...\nAGENT: ..."
            lines = summary.strip().split("\n")
            for line in lines:
                if line.startswith("USER"):
                    user_summary = line.replace("USER asked:", "").replace("USER asked", "").replace("USER:", "").strip()
                elif line.startswith("AGENT"):
                    agent_summary = line.replace("AGENT:", "").strip()

    session_data = {
        "sessionId": session_id,
        "cwd": cwd,
        "status": status,
        "summary": summary,  # Keep raw for backwards compat
        "userSummary": user_summary,
        "agentSummary": agent_summary,
        "updatedAt": datetime.now().isoformat()
    }

    try:
        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2)
        debug_log(f"Wrote session file: {session_file}")
    except Exception as e:
        debug_log(f"Error writing session file: {e}")


def read_project_context(cwd: str) -> dict:
    """Read CLAUDE.md and PLAN.md for project context."""
    context = {
        "claude_md": "",
        "plan_md": "",
        "current_task": ""
    }

    # Read CLAUDE.md (project instructions)
    claude_path = os.path.join(cwd, "CLAUDE.md")
    if os.path.exists(claude_path):
        try:
            with open(claude_path, "r") as f:
                content = f.read()
                # Take first 2000 chars - usually has project name and key info
                context["claude_md"] = content[:2000]
        except Exception:
            pass

    # Read PLAN.md
    plan_path = os.path.join(cwd, "PLAN.md")
    if os.path.exists(plan_path):
        try:
            with open(plan_path, "r") as f:
                content = f.read()
                context["plan_md"] = content[:3000]

                # Extract just the CURRENT section for focused context
                match = re.search(r'## CURRENT[:\s].*?(?=\n## |\n---|\Z)', content, re.DOTALL | re.IGNORECASE)
                if match:
                    context["current_task"] = match.group(0).strip()[:1000]
        except Exception:
            pass

    return context


def extract_last_assistant_response(transcript_path: str) -> str:
    """Extract the last assistant response from JSONL transcript."""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""

    last_response = ""
    try:
        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Check for assistant messages - type is "assistant" in Claude Code transcripts
                    if entry.get("type") == "assistant":
                        message = entry.get("message", {})
                        content = message.get("content", [])
                        if isinstance(content, list):
                            texts = []
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    texts.append(c.get("text", ""))
                            if texts:
                                last_response = "\n".join(texts)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

    return last_response


def build_conversation_text(exchanges: list) -> str:
    """Build formatted conversation text from exchanges."""
    parts = []
    for ex in exchanges:
        if ex.get("user") and ex.get("assistant"):
            # Only include complete exchanges
            parts.append(f"USER: {ex['user']}\nAGENT: {ex['assistant']}")
    return "\n\n".join(parts)


def generate_summary(conversation_text: str, project_context: dict) -> str:
    """Call Claude Code CLI to generate a brief 2-line summary with project context."""
    # Truncate conversation if too long
    max_conversation_len = 6000
    if len(conversation_text) > max_conversation_len:
        conversation_text = conversation_text[:max_conversation_len] + "..."

    # Build context section
    context_parts = []
    if project_context.get("current_task"):
        context_parts.append(f"CURRENT TASK:\n{project_context['current_task']}")
    elif project_context.get("plan_md"):
        context_parts.append(f"PROJECT PLAN:\n{project_context['plan_md'][:500]}")

    if project_context.get("claude_md"):
        # Extract just the project name/description from CLAUDE.md
        claude_excerpt = project_context["claude_md"][:500]
        context_parts.append(f"PROJECT INFO:\n{claude_excerpt}")

    context_section = "\n\n".join(context_parts) if context_parts else ""

    summary_prompt = f"""Summarize this coding session in MINIMAL words.
{f"{chr(10)}PROJECT: {context_section[:300]}{chr(10)}" if context_section else ""}
CONVERSATION:
{conversation_text}

CRITICAL: Be EXTREMELY concise. Max 8-10 words each. No filler words. Telegraph style.

Respond with ONLY valid JSON, no markdown, no code fences:
{{"user_summary": "max 10 words - what user wanted", "agent_summary": "max 10 words - what was done"}}

Examples of good summaries:
- "user_summary": "Add dark mode toggle"
- "agent_summary": "Implemented theme switcher in settings"

- "user_summary": "Fix login crash on iOS"
- "agent_summary": "Fixed nil pointer in auth flow"

Be this concise."""

    try:
        # Find claude CLI (handles pyenv/homebrew/npm path issues)
        claude_bin = find_claude_cli()
        debug_log(f"Using claude CLI: {claude_bin}")

        # Call Claude Code CLI in one-shot mode using PTY to prevent /dev/tty blocking
        # Claude opens /dev/tty directly causing hangs - we detach from controlling terminal
        # See: https://github.com/anthropics/claude-code/issues/13598
        env = os.environ.copy()
        # CRITICAL: Disable hooks for this nested Claude call to prevent infinite recursion
        env["CLAUDE_HOOK_SKIP"] = "1"

        before_claude = datetime.now()
        debug_log("Creating PTY for claude CLI call...")

        try:
            # Create pseudo-terminal pair
            master_fd, slave_fd = pty.openpty()
            debug_log(f"PTY created: master={master_fd}, slave={slave_fd}")

            # Spawn claude with PTY and detach from controlling terminal
            process = subprocess.Popen(
                [
                    claude_bin, "-p",
                    "--model", CLAUDE_MODEL,
                    "--no-session-persistence",  # Don't save this as a session
                    summary_prompt
                ],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,  # CRITICAL: Detach from controlling terminal (prevents /dev/tty access)
                env=env,
                close_fds=False  # Keep slave fd open for child
            )
            debug_log(f"Process spawned with PID={process.pid}")

            # Close slave fd in parent (child keeps it open)
            os.close(slave_fd)

            # Make master fd non-blocking
            os.set_blocking(master_fd, False)

            # Read from master fd with timeout
            output_bytes = b""
            timeout_duration = 90  # Increased from 15s - claude -p takes 40-50s even for simple prompts
            timeout_start = time.time()
            poll_interval = 0.1

            debug_log(f"Starting read loop with {timeout_duration}s timeout...")
            while time.time() - timeout_start < timeout_duration:
                # Check if process is still running
                if process.poll() is not None:
                    debug_log(f"Process exited with code {process.returncode}")
                    # Process finished, do final read
                    try:
                        while True:
                            chunk = os.read(master_fd, 4096)
                            if not chunk:
                                break
                            output_bytes += chunk
                    except (BlockingIOError, OSError):
                        pass
                    break

                # Try to read data
                try:
                    chunk = os.read(master_fd, 4096)
                    if chunk:
                        output_bytes += chunk
                        debug_log(f"Read {len(chunk)} bytes (total: {len(output_bytes)})")
                except BlockingIOError:
                    # No data available yet
                    time.sleep(poll_interval)
                except OSError as e:
                    debug_log(f"OSError during read: {e}")
                    break

            # Close master fd
            os.close(master_fd)

            # Check for timeout
            if process.poll() is None:
                debug_log("TIMEOUT - killing process")
                process.kill()
                process.wait()
                return f"USER asked: (see conversation)\nAGENT: (Claude CLI timeout after {timeout_duration}s)"

            # Process finished successfully
            after_claude = datetime.now()
            elapsed = (after_claude - before_claude).total_seconds()
            debug_log(f"Claude CLI took: {elapsed:.4f}s")

            # Decode output and strip ANSI escape codes from PTY
            stdout = output_bytes.decode('utf-8', errors='replace')
            # Remove ANSI escape sequences in multiple passes
            # Pass 1: Remove full ANSI sequences (ESC-based)
            ansi_escape_1 = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07\x1B]*(?:\x07|\x1B\\))')
            stdout_temp = ansi_escape_1.sub('', stdout)
            # Pass 2: Remove trailing terminal garbage lines (e.g., "9;4;0;" with BEL)
            ansi_escape_2 = re.compile(r'\r?\n[0-9;]+[\x00-\x1F]*$')
            stdout_clean = ansi_escape_2.sub('', stdout_temp)
            debug_log(f"Claude CLI finished with returncode={process.returncode}, stdout_len={len(stdout)}, clean_len={len(stdout_clean)}")

            if process.returncode == 0 and stdout_clean.strip():
                # Success
                clean_output = stdout_clean.strip()
                debug_log(f"SUCCESS - got output: {clean_output[:100]}")
                return clean_output
            else:
                debug_log(f"Claude CLI error: returncode={process.returncode}")
                debug_log(f"stdout: {stdout_clean[:500]}")
                return f"USER asked: (see conversation)\nAGENT: (Claude CLI error: {process.returncode})"

        except Exception as e:
            debug_log(f"Exception in PTY handling: {type(e).__name__}: {e}")
            return f"USER asked: (see conversation)\nAGENT: (PTY error: {e})"

    except FileNotFoundError:
        debug_log(f"Claude CLI NOT FOUND at: {claude_bin}")
        return "USER asked: (see conversation)\nAGENT: (Claude CLI not found)"
    except Exception as e:
        debug_log(f"Claude CLI exception: {e}")
        return f"USER asked: (see conversation)\nAGENT: (error: {e})"


def _run_summary_pipeline(session_id: str, transcript_path: str, cwd_from_input: str):
    """Run the full summary pipeline. Raises on failure so caller can handle."""
    # Read conversation from UserPromptSubmit hook
    temp_file = f"/tmp/claude-{session_id}-conversation.json"
    debug_log(f"Looking for conversation file: {temp_file}")

    if not os.path.exists(temp_file):
        debug_log(f"Conversation file not found: {temp_file}")
        return

    debug_log("Found conversation file")

    try:
        with open(temp_file, "r") as f:
            conversation = json.load(f)
        debug_log(f"Loaded conversation: {len(conversation.get('exchanges', []))} exchanges")
    except (json.JSONDecodeError, FileNotFoundError) as e:
        debug_log(f"Error reading conversation file: {e}")
        return

    cwd = conversation.get("cwd", cwd_from_input)
    exchanges = conversation.get("exchanges", [])
    debug_log(f"Conversation data - cwd: {cwd}, exchanges: {len(exchanges)}")

    if not cwd or not exchanges:
        debug_log(f"Missing required data - cwd: {bool(cwd)}, exchanges: {bool(exchanges)}")
        # Still write waiting status with no summary
        if cwd:
            write_session_file(session_id, cwd, "waiting", None)
        return

    # Extract last assistant response from transcript
    debug_log(f"Extracting assistant response from transcript: {transcript_path}")
    assistant_response = extract_last_assistant_response(transcript_path)
    debug_log(f"Assistant response length: {len(assistant_response) if assistant_response else 0}")

    if not assistant_response:
        debug_log("No assistant response found - marking waiting without summary")
        write_session_file(session_id, cwd, "waiting", None)
        return

    # Fill in the assistant response for the last exchange
    if exchanges and exchanges[-1].get("assistant") is None:
        exchanges[-1]["assistant"] = assistant_response
        debug_log("Filled in assistant response for last exchange")

    # Save updated conversation back
    conversation["exchanges"] = exchanges
    try:
        with open(temp_file, "w") as f:
            json.dump(conversation, f)
        debug_log("Updated conversation file")
    except Exception as e:
        debug_log(f"Error updating conversation: {e}")

    # Build conversation text for summary (all complete exchanges)
    conversation_text = build_conversation_text(exchanges)
    debug_log(f"Built conversation text: {len(conversation_text)} chars")

    if not conversation_text:
        debug_log("No conversation text to summarize")
        write_session_file(session_id, cwd, "waiting", None)
        return

    # Read project context (CLAUDE.md and PLAN.md)
    debug_log(f"Reading project context from: {cwd}")
    project_context = read_project_context(cwd)
    debug_log(f"Project context loaded - claude_md: {len(project_context.get('claude_md', ''))}, plan_md: {len(project_context.get('plan_md', ''))}")

    # Generate summary using Claude Haiku
    debug_log("Calling Claude Haiku to generate summary...")
    summary = generate_summary(conversation_text, project_context)
    debug_log(f"Generated summary: {len(summary)} chars")

    # Write slim summary to .claude/SUMMARY.txt (for HUD display)
    output_dir = os.path.join(cwd, ".claude")
    os.makedirs(output_dir, exist_ok=True)

    summary_path = os.path.join(output_dir, "SUMMARY.txt")
    debug_log(f"Writing summary to: {summary_path}")

    try:
        with open(summary_path, "w") as f:
            f.write(summary)
        debug_log("Successfully wrote summary file")
    except Exception as e:
        debug_log(f"Error writing summary: {e}")

    # Write session file for Whisper Village session dots
    write_session_file(session_id, cwd, "waiting", summary)


def main():
    start_time = datetime.now()
    debug_log(f"Stop Hook STARTED at {start_time.strftime('%H:%M:%S.%f')}")

    # Prevent recursive hook execution from nested claude CLI calls
    if os.environ.get("CLAUDE_HOOK_SKIP") == "1":
        debug_log("CLAUDE_HOOK_SKIP detected, exiting immediately")
        sys.exit(0)

    # Ensure common binary locations are in PATH (hooks may run with stripped environment)
    extra_paths = [
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.claude/local"),
        "/usr/local/bin",
        os.path.expanduser("~/.npm-global/bin"),
    ]
    current_path = os.environ.get("PATH", "")
    for p in extra_paths:
        if p not in current_path:
            current_path = f"{p}:{current_path}"
    os.environ["PATH"] = current_path

    after_path = datetime.now()
    debug_log(f"Path setup took: {(after_path - start_time).total_seconds():.4f}s")

    try:
        stdin_data = sys.stdin.read()
        after_stdin = datetime.now()
        debug_log(f"Reading stdin took: {(after_stdin - after_path).total_seconds():.4f}s")

        input_data = json.loads(stdin_data)
        after_parse = datetime.now()
        debug_log(f"Parsing JSON took: {(after_parse - after_stdin).total_seconds():.4f}s")
    except json.JSONDecodeError as e:
        debug_log(f"JSON decode error: {e}")
        sys.exit(0)
    except Exception as e:
        debug_log(f"Unexpected error reading input: {e}")
        sys.exit(0)

    session_id = input_data.get("session_id", "unknown")
    transcript_path = input_data.get("transcript_path", "")
    cwd = input_data.get("cwd", os.getcwd())

    # IMMEDIATELY mark session as "waiting" — this is the critical path
    # The dot must turn green as soon as the agent stops, regardless of summary generation
    before_session = datetime.now()
    write_session_file(session_id, cwd, "waiting", None)
    after_session = datetime.now()
    debug_log(f"Writing session file took: {(after_session - before_session).total_seconds():.4f}s")

    # Fork summary generation into a background process so the hook exits instantly
    # The parent (hook) exits immediately, the child generates the summary async
    before_fork = datetime.now()
    pid = os.fork()
    after_fork = datetime.now()
    debug_log(f"Fork took: {(after_fork - before_fork).total_seconds():.4f}s")

    if pid == 0:
        # Child process — detach from parent and generate summary
        try:
            os.setsid()  # Create new session, fully detach from hook process group
            debug_log("Background summary process started (detached)")
            _run_summary_pipeline(session_id, transcript_path, cwd)
            debug_log("Background summary process FINISHED")
        except Exception as e:
            debug_log(f"Background summary error: {e}")
        finally:
            os._exit(0)  # Exit child without cleanup (don't trigger atexit handlers)
    else:
        # Parent (hook) — exit immediately, don't wait for child
        debug_log(f"Forked summary to background pid={pid}, hook exiting now")
        end_time = datetime.now()
        total_time = (end_time - start_time).total_seconds()
        debug_log(f"Stop Hook FINISHED - Total time: {total_time:.4f}s")

    # Note: We keep temp_file to accumulate exchanges over time
    # user_prompt_submit.py handles trimming to MAX_EXCHANGES

    sys.exit(0)


if __name__ == "__main__":
    main()
