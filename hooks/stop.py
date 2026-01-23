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
    """Log debugging info with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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

        # Call Claude Code CLI in one-shot mode
        # Use Popen for better timeout handling - subprocess.run timeout can leave zombies
        env = os.environ.copy()
        process = subprocess.Popen(
            [
                claude_bin, "-p",
                "--model", CLAUDE_MODEL,
                "--no-session-persistence",  # Don't save this as a session
                summary_prompt
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,  # Prevent any stdin blocking
            text=True,
            env=env
        )

        try:
            stdout, stderr = process.communicate(timeout=45)
            debug_log(f"Claude CLI finished with returncode={process.returncode}, stdout_len={len(stdout)}, stderr_len={len(stderr)}")

            if process.returncode == 0 and stdout.strip():
                return stdout.strip()
            else:
                debug_log(f"Claude CLI error: returncode={process.returncode}, stderr={stderr[:200]}")
                return f"USER asked: (see conversation)\nAGENT: (Claude CLI error: {process.returncode})"
        except subprocess.TimeoutExpired:
            debug_log("Claude CLI TIMEOUT - killing process")
            process.kill()
            process.wait()
            return "USER asked: (see conversation)\nAGENT: (Claude CLI timeout after 45s)"

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

    debug_log("Stop Hook STARTED")
    debug_log(f"Arguments: {sys.argv}")
    debug_log(f"Environment: PWD={os.getcwd()}, PATH={os.environ.get('PATH', '')}")

    try:
        stdin_data = sys.stdin.read()
        debug_log(f"Raw stdin data: {stdin_data[:200]}...")

        input_data = json.loads(stdin_data)
        debug_log(f"Parsed input: {input_data}")
    except json.JSONDecodeError as e:
        debug_log(f"JSON decode error: {e}")
        sys.exit(0)
    except Exception as e:
        debug_log(f"Unexpected error reading input: {e}")
        sys.exit(0)

    session_id = input_data.get("session_id", "unknown")
    transcript_path = input_data.get("transcript_path", "")
    cwd = input_data.get("cwd", os.getcwd())
    debug_log(f"Extracted - session_id: {session_id}, transcript_path: {transcript_path}, cwd: {cwd}")

    # Always mark session as "waiting" when stop fires, even if summary fails
    # This prevents dots from staying orange forever
    try:
        _run_summary_pipeline(session_id, transcript_path, cwd)
    except Exception as e:
        debug_log(f"Summary pipeline error: {e}")
        # Still mark as waiting even on failure
        write_session_file(session_id, cwd, "waiting", None)

    debug_log("Stop Hook FINISHED")

    # Note: We keep temp_file to accumulate exchanges over time
    # user_prompt_submit.py handles trimming to MAX_EXCHANGES

    sys.exit(0)


if __name__ == "__main__":
    main()
