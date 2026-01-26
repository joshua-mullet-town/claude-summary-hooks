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
    """Log debugging info with timestamp (only if CLAUDE_HOOK_DEBUG=1)"""
    if os.environ.get("CLAUDE_HOOK_DEBUG") != "1":
        return
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
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
    start_time = datetime.datetime.now()
    debug_log(f"UserPromptSubmit Hook STARTED at {start_time.strftime('%H:%M:%S.%f')}")

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

    after_path = datetime.datetime.now()
    debug_log(f"Path setup took: {(after_path - start_time).total_seconds():.4f}s")

    try:
        stdin_data = sys.stdin.read()
        after_stdin = datetime.datetime.now()
        debug_log(f"Reading stdin took: {(after_stdin - after_path).total_seconds():.4f}s")

        input_data = json.loads(stdin_data)
        after_parse = datetime.datetime.now()
        debug_log(f"Parsing JSON took: {(after_parse - after_stdin).total_seconds():.4f}s")
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
    before_file_ops = datetime.datetime.now()

    # Load existing conversation or start fresh
    conversation = {
        "cwd": cwd,
        "session_id": session_id,
        "exchanges": []  # List of {"user": ..., "assistant": ...}
    }

    if os.path.exists(temp_file):
        try:
            with open(temp_file, "r") as f:
                conversation = json.load(f)
            after_file_read = datetime.datetime.now()
            debug_log(f"Reading conversation file took: {(after_file_read - before_file_ops).total_seconds():.4f}s")
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

    before_write = datetime.datetime.now()

    try:
        with open(temp_file, "w") as f:
            json.dump(conversation, f)
        after_write = datetime.datetime.now()
        debug_log(f"Writing conversation file took: {(after_write - before_write).total_seconds():.4f}s")
    except Exception as e:
        debug_log(f"Error writing conversation file: {e}")

    # Write session file with "working" status for Whisper Village
    before_session = datetime.datetime.now()
    write_session_file(session_id, cwd, "working")
    after_session = datetime.datetime.now()
    debug_log(f"Writing session file took: {(after_session - before_session).total_seconds():.4f}s")

    end_time = datetime.datetime.now()
    total_time = (end_time - start_time).total_seconds()
    debug_log(f"UserPromptSubmit Hook FINISHED - Total time: {total_time:.4f}s")
    sys.exit(0)


if __name__ == "__main__":
    main()
