#!/bin/bash
#
# claude-summary-hooks diagnostic tool
# Run this on any machine to identify why hooks aren't working
#

echo "=== Claude Summary Hooks Diagnostics ==="
echo "Date: $(date)"
echo "Machine: $(hostname)"
echo ""

# 1. Check settings.json
echo "--- settings.json hooks ---"
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
    if command -v jq >/dev/null 2>&1; then
        echo "Stop hooks:"
        jq '.hooks.Stop' "$SETTINGS" 2>/dev/null
        echo ""
        echo "UserPromptSubmit hooks:"
        jq '.hooks.UserPromptSubmit' "$SETTINGS" 2>/dev/null
    else
        echo "(jq not installed, showing raw)"
        cat "$SETTINGS"
    fi
else
    echo "ERROR: $SETTINGS not found!"
fi
echo ""

# 2. Check hook files exist
echo "--- Hook files ---"
for f in "$HOME/.claude/hooks/stop.py" "$HOME/.claude/hooks/user_prompt_submit.py" "$HOME/.claude/hooks/combined-stop.sh"; do
    if [ -f "$f" ]; then
        echo "EXISTS: $f"
    else
        echo "MISSING: $f"
    fi
done
echo ""

# 3. Check python3
echo "--- Python3 ---"
echo "which python3: $(which python3 2>/dev/null || echo 'NOT FOUND')"
echo "python3 --version: $(python3 --version 2>/dev/null || echo 'FAILED')"
if command -v pyenv >/dev/null 2>&1; then
    echo "pyenv which python3: $(pyenv which python3 2>/dev/null || echo 'FAILED')"
fi
echo "sys.executable: $(python3 -c 'import sys; print(sys.executable)' 2>/dev/null || echo 'FAILED')"

# Check the python path in settings.json
if command -v jq >/dev/null 2>&1 && [ -f "$SETTINGS" ]; then
    CONFIGURED_CMD=$(jq -r '.hooks.Stop[0].hooks[0].command // "none"' "$SETTINGS" 2>/dev/null)
    echo "Configured stop command: $CONFIGURED_CMD"
    # Extract python path from command
    CONFIGURED_PYTHON=$(echo "$CONFIGURED_CMD" | awk '{print $1}')
    if [ -f "$CONFIGURED_PYTHON" ]; then
        echo "Configured python EXISTS: $CONFIGURED_PYTHON"
        echo "  Version: $($CONFIGURED_PYTHON --version 2>/dev/null)"
    else
        echo "ERROR: Configured python NOT FOUND: $CONFIGURED_PYTHON"
    fi
fi
echo ""

# 4. Check claude CLI
echo "--- Claude CLI ---"
echo "which claude: $(which claude 2>/dev/null || echo 'NOT FOUND')"
for p in "$HOME/.claude/local/claude" "$HOME/.local/bin/claude" "/usr/local/bin/claude" "$HOME/.npm-global/bin/claude"; do
    if [ -f "$p" ]; then
        echo "FOUND: $p"
    fi
done
echo ""

# 5. Check debug logs
echo "--- Recent debug logs ---"
echo ""
echo "user_prompt_submit log (last 10 lines):"
if [ -f /tmp/claude-debug-user-prompt.log ]; then
    tail -10 /tmp/claude-debug-user-prompt.log
else
    echo "(no log file found)"
fi
echo ""
echo "stop hook log (last 20 lines):"
if [ -f /tmp/claude-debug-stop.log ]; then
    tail -20 /tmp/claude-debug-stop.log
else
    echo "(no log file found)"
fi
echo ""

# 6. Check session files
echo "--- Session files ---"
SESSIONS_DIR="$HOME/.claude/sessions"
if [ -d "$SESSIONS_DIR" ]; then
    echo "Session files found:"
    ls -la "$SESSIONS_DIR"/ 2>/dev/null
    echo ""
    echo "Latest session content:"
    LATEST=$(ls -t "$SESSIONS_DIR"/*.json 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        cat "$LATEST"
    else
        echo "(no session files)"
    fi
else
    echo "No sessions directory found"
fi
echo ""

# 7. Check conversation temp files
echo "--- Conversation temp files ---"
ls -la /tmp/claude-*-conversation.json 2>/dev/null || echo "(none found)"
echo ""

# 8. Try running the hook manually
echo "--- Manual hook test ---"
STOP_CMD=$(jq -r '.hooks.Stop[0].hooks[0].command // "none"' "$SETTINGS" 2>/dev/null)
if [ "$STOP_CMD" != "none" ]; then
    PYTHON_BIN=$(echo "$STOP_CMD" | awk '{print $1}')
    HOOK_SCRIPT=$(echo "$STOP_CMD" | awk '{print $2}')
    echo "Testing: $PYTHON_BIN $HOOK_SCRIPT"
    echo '{"session_id":"test-diag","transcript_path":"","cwd":"/tmp"}' | timeout 5 $PYTHON_BIN "$HOOK_SCRIPT" 2>&1
    echo "Exit code: $?"
    echo ""
    echo "Debug log after test:"
    tail -5 /tmp/claude-debug-stop.log 2>/dev/null
fi

echo ""
echo "=== Diagnostics Complete ==="
echo ""
echo "Copy everything above and paste it to me."
