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

def debug_log(message):
    """Log debugging info with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DEBUG_LOG, "a") as f:
        f.write(f"[{timestamp}] {message}\n")
        f.flush()


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

    summary_prompt = f"""Summarize this coding session.
{f"{chr(10)}PROJECT: {context_section[:300]}{chr(10)}" if context_section else ""}
CONVERSATION:
{conversation_text}

Respond with EXACTLY two lines, no other text:
USER asked [one sentence - what user wanted across the session]
AGENT [one sentence - what was accomplished]"""

    try:
        # Call Claude Code CLI in one-shot mode
        result = subprocess.run(
            [
                "claude", "-p",
                "--model", CLAUDE_MODEL,
                "--tools", "",  # Disable tools, just text generation
                "--no-session-persistence",  # Don't save this as a session
                summary_prompt
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return result.stdout.strip()
        else:
            debug_log(f"Claude CLI error: {result.stderr}")
            return f"USER asked: (see conversation)\nAGENT: (Claude CLI error: {result.returncode})"

    except subprocess.TimeoutExpired:
        return "USER asked: (see conversation)\nAGENT: (Claude CLI timeout)"
    except FileNotFoundError:
        return "USER asked: (see conversation)\nAGENT: (Claude CLI not found)"
    except Exception as e:
        return f"USER asked: (see conversation)\nAGENT: (error: {e})"


def main():
    debug_log("Stop Hook STARTED")
    debug_log(f"Arguments: {sys.argv}")
    debug_log(f"Environment: PWD={os.getcwd()}")

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
    debug_log(f"Extracted - session_id: {session_id}, transcript_path: {transcript_path}")

    # Read conversation from UserPromptSubmit hook
    temp_file = f"/tmp/claude-{session_id}-conversation.json"
    debug_log(f"Looking for conversation file: {temp_file}")

    if not os.path.exists(temp_file):
        debug_log(f"Conversation file not found: {temp_file}")
        sys.exit(0)

    debug_log("Found conversation file")

    try:
        with open(temp_file, "r") as f:
            conversation = json.load(f)
        debug_log(f"Loaded conversation: {len(conversation.get('exchanges', []))} exchanges")
    except (json.JSONDecodeError, FileNotFoundError) as e:
        debug_log(f"Error reading conversation file: {e}")
        sys.exit(0)

    cwd = conversation.get("cwd", "")
    exchanges = conversation.get("exchanges", [])
    debug_log(f"Conversation data - cwd: {cwd}, exchanges: {len(exchanges)}")

    if not cwd or not exchanges:
        debug_log(f"Missing required data - cwd: {bool(cwd)}, exchanges: {bool(exchanges)}")
        sys.exit(0)

    # Extract last assistant response from transcript
    debug_log(f"Extracting assistant response from transcript: {transcript_path}")
    assistant_response = extract_last_assistant_response(transcript_path)
    debug_log(f"Assistant response length: {len(assistant_response) if assistant_response else 0}")

    if not assistant_response:
        debug_log("No assistant response found")
        sys.exit(0)

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
        sys.exit(0)

    # Read project context (CLAUDE.md and PLAN.md)
    debug_log(f"Reading project context from: {cwd}")
    project_context = read_project_context(cwd)
    debug_log(f"Project context loaded - claude_md: {len(project_context.get('claude_md', ''))}, plan_md: {len(project_context.get('plan_md', ''))}")

    # Generate summary using Ollama (local, no infinite loop risk)
    debug_log("Calling Ollama to generate summary...")
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

    debug_log("Stop Hook FINISHED")

    # Note: We keep temp_file to accumulate exchanges over time
    # user_prompt_submit.py handles trimming to MAX_EXCHANGES

    sys.exit(0)


if __name__ == "__main__":
    main()
