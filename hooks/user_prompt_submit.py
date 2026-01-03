#!/usr/bin/env python3
"""
UserPromptSubmit Hook - Message Assistant
Captures the user's prompt and appends to conversation history (last 5 exchanges).
"""

import json
import sys
import os
import datetime

MAX_EXCHANGES = 5  # Keep last 5 user/assistant pairs
DEBUG_LOG = "/tmp/claude-debug-user-prompt.log"

def debug_log(message):
    """Log debugging info with timestamp"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DEBUG_LOG, "a") as f:
        f.write(f"[{timestamp}] {message}\n")
        f.flush()

def main():
    debug_log("UserPromptSubmit Hook STARTED")
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

    debug_log("UserPromptSubmit Hook FINISHED")
    sys.exit(0)


if __name__ == "__main__":
    main()
