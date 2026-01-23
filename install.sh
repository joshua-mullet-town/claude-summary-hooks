#!/bin/bash
#
# claude-summary-hooks installer
# Installs Claude Code hooks for session summary generation
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$HOME/.claude/hooks"
SETTINGS_FILE="$HOME/.claude/settings.json"
BIN_DIR="$HOME/.local/bin"

# Pull latest from GitHub before installing
if [ -d "$SCRIPT_DIR/.git" ]; then
    echo "Pulling latest version from GitHub..."
    (cd "$SCRIPT_DIR" && git pull --ff-only 2>/dev/null) && echo "  Updated to latest version" || echo "  (already up to date or offline)"
fi

echo "Installing claude-summary-hooks..."

# Create directories
mkdir -p "$HOOKS_DIR"
mkdir -p "$BIN_DIR"

# Copy hook files
cp "$SCRIPT_DIR/hooks/user_prompt_submit.py" "$HOOKS_DIR/"
cp "$SCRIPT_DIR/hooks/stop.py" "$HOOKS_DIR/"
chmod +x "$HOOKS_DIR/user_prompt_submit.py"
chmod +x "$HOOKS_DIR/stop.py"

echo "  Installed hooks to $HOOKS_DIR"

# Install the claude-summary command
cp "$SCRIPT_DIR/bin/claude-summary" "$BIN_DIR/"
chmod +x "$BIN_DIR/claude-summary"

echo "  Installed claude-summary to $BIN_DIR"

# Update Claude settings.json (preserving existing hooks)
if ! command -v jq >/dev/null 2>&1; then
    echo "  WARNING: jq not found, skipping settings.json update"
    echo "  Install jq (brew install jq) and re-run, or manually configure hooks"
else
    # Create settings file if it doesn't exist
    if [ ! -f "$SETTINGS_FILE" ]; then
        mkdir -p "$(dirname "$SETTINGS_FILE")"
        echo '{}' > "$SETTINGS_FILE"
    fi

    EXISTING=$(cat "$SETTINGS_FILE")

    # Resolve python3 to REAL path (not pyenv shim) for portability
    # pyenv shims won't work in Claude Code hook subprocesses
    if command -v pyenv >/dev/null 2>&1; then
        # Get the actual python3 binary pyenv resolves to
        PYTHON3_PATH=$(pyenv which python3 2>/dev/null || command -v python3 2>/dev/null || echo "/usr/bin/python3")
    else
        PYTHON3_PATH=$(command -v python3 2>/dev/null || echo "/usr/bin/python3")
    fi
    # Follow symlinks to get the true path
    if [ -L "$PYTHON3_PATH" ]; then
        PYTHON3_PATH=$(readlink -f "$PYTHON3_PATH" 2>/dev/null || python3 -c "import sys; print(sys.executable)" 2>/dev/null || echo "$PYTHON3_PATH")
    fi
    echo "  Using Python: $PYTHON3_PATH"

    # Add UserPromptSubmit hook (replace - we own this hook type entirely)
    EXISTING=$(echo "$EXISTING" | jq --arg cmd "$PYTHON3_PATH $HOOKS_DIR/user_prompt_submit.py" '
        .hooks.UserPromptSubmit = [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": $cmd,
                        "timeout": 10
                    }
                ]
            }
        ]
    ')

    # Add Stop hook (replace existing summary hook if present)
    # Remove any existing stop.py hooks first, then add fresh
    EXISTING=$(echo "$EXISTING" | jq --arg cmd "$PYTHON3_PATH $HOOKS_DIR/stop.py" '
        .hooks.Stop = (
            [(.hooks.Stop // [])[] | select(.hooks[0].command | contains("stop.py") | not)]
            + [{
                "matcher": "*",
                "hooks": [{
                    "type": "command",
                    "command": $cmd,
                    "timeout": 30
                }]
            }]
        )
    ')

    echo "$EXISTING" > "$SETTINGS_FILE"
    echo "  Updated Claude settings (preserving existing hooks)"
fi

# Check for Claude CLI
echo ""
if command -v claude >/dev/null 2>&1; then
    echo "Claude CLI found!"
else
    echo "WARNING: Claude CLI not found!"
    echo "  The summary hooks use 'claude -p --model haiku' to generate summaries."
    echo "  Make sure Claude Code CLI is installed and in your PATH."
fi

echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Restart Claude Code to pick up the new hooks"
echo "  2. Summaries will appear in .claude/SUMMARY.txt after each session"
echo "  3. Run 'claude-summary' in any project for live streaming view"
echo ""
echo "Make sure $BIN_DIR is in your PATH:"
echo '  export PATH="$HOME/.local/bin:$PATH"'
