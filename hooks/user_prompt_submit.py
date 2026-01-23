#!/usr/bin/env python3
"""
UserPromptSubmit Hook - Message Assistant
Captures the user's prompt and appends to conversation history (last 5 exchanges).
Also writes session status to ~/.claude/sessions/ for Whisper Village.
"""

import json
import sys
import os
import datetime
import hashlib

MAX_EXCHANGES = 5  # Keep last 5 user/assistant pairs
DEBUG_LOG = "/tmp/claude-debug-user-prompt.log"

def debug_log(message):
    """Log debugging info with timestamp"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DEBUG_LOG, "a") as f:
        f.write(f"[{timestamp}] {message}\n")
        f.flush()


def write_session_file(session_id: str, cwd: str, status: str, summary: str = None):
    """Write session state to ~/.claude/sessions/ for Whisper Village to read."""
    sessions_dir = os.path.expanduser("~/.claude/sessions")
    os.makedirs(sessions_dir, exist_ok=True)

    # Use a hash of cwd as filename to avoid path issues
    cwd_hash = hashlib.md5(cwd.encode()).hexdigest()[:12]
    session_file = os.path.join(sessions_dir, f"{cwd_hash}.json")

    # Read existing summary if available
    existing_summary = summary
    if not existing_summary and os.path.exists(session_file):
        try:
            with open(session_file, "r") as f:
                existing_data = json.load(f)
                existing_summary = existing_data.get("summary")
        except:
            pass

    session_data = {
        "sessionId": session_id,
        "cwd": cwd,
        "status": status,
        "summary": existing_summary,
        "updatedAt": datetime.datetime.now().isoformat()
    }

    try:
        with open(session_file, "w") as f:
            json.dump(session_data, f, indent=2)
        debug_log(f"Wrote session file: {session_file} (status: {status})")
    except Exception as e:
        debug_log(f"Error writing session file: {e}")

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

    debug_log("UserPromptSubmit Hook STARTED")
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

    prompt = input_data.get("prompt", "")
    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", os.getcwd())

    debug_log(f"Extracted - prompt: '{prompt[:100]}...', session_id: {session_id}, cwd: {cwd}")

    if not prompt:
        debug_log("No prompt provided, exiting")
        sys.exit(0)

    temp_file = f"/tmp/claude-{session_id}-conversation.json"
    debug_log(f"Using temp file: {temp_file}")

    # Load existing conversation or start fresh
    conversation = {
        "cwd": cwd,
        "session_id": session_id,
        "exchanges": []  # List of {"user": ..., "assistant": ...}
    }

    if os.path.exists(temp_file):
        debug_log(f"Found existing conversation file")
        try:
            with open(temp_file, "r") as f:
                conversation = json.load(f)
                debug_log(f"Loaded existing conversation with {len(conversation.get('exchanges', []))} exchanges")
        except (json.JSONDecodeError, FileNotFoundError) as e:
            debug_log(f"Error loading existing conversation: {e}")
    else:
        debug_log("Creating new conversation file")

    # Add new user message as pending exchange
    new_exchange = {
        "user": prompt,
        "assistant": None  # Will be filled by Stop hook
    }
    conversation["exchanges"].append(new_exchange)
    debug_log(f"Added new exchange. Total exchanges: {len(conversation['exchanges'])}")

    # Keep only last N exchanges
    conversation["exchanges"] = conversation["exchanges"][-MAX_EXCHANGES:]
    conversation["cwd"] = cwd  # Update in case it changed

    debug_log(f"Final conversation: {len(conversation['exchanges'])} exchanges")

    try:
        with open(temp_file, "w") as f:
            json.dump(conversation, f)
        debug_log(f"Successfully wrote conversation to {temp_file}")
    except Exception as e:
        debug_log(f"Error writing conversation file: {e}")

    # Write session file with "working" status for Whisper Village
    write_session_file(session_id, cwd, "working")

    debug_log("UserPromptSubmit Hook FINISHED")
    sys.exit(0)


if __name__ == "__main__":
    main()
