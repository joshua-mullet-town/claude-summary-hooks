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

# Update Claude settings.json
if [ -f "$SETTINGS_FILE" ]; then
    # Check if we have jq for JSON manipulation
    if command -v jq >/dev/null 2>&1; then
        # Read existing settings and add/update hooks
        TEMP_FILE=$(mktemp)

        # Add UserPromptSubmit hook if not present
        jq --arg hook "$HOOKS_DIR/user_prompt_submit.py" '
            .hooks.UserPromptSubmit = [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": ("python3 " + $hook),
                            "timeout": 10
                        }
                    ]
                }
            ]
        ' "$SETTINGS_FILE" > "$TEMP_FILE"

        # Add Stop hook (preserving existing ones)
        jq --arg hook "$HOOKS_DIR/stop.py" '
            if .hooks.Stop then
                # Check if our hook already exists
                if (.hooks.Stop | map(select(.hooks[]?.command | contains("stop.py"))) | length) > 0 then
                    .
                else
                    .hooks.Stop += [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": ("python3 " + $hook),
                                    "timeout": 30
                                }
                            ]
                        }
                    ]
                end
            else
                .hooks.Stop = [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": ("python3 " + $hook),
                                "timeout": 30
                            }
                        ]
                    }
                ]
            end
        ' "$TEMP_FILE" > "${TEMP_FILE}.2"

        mv "${TEMP_FILE}.2" "$SETTINGS_FILE"
        rm -f "$TEMP_FILE"

        echo "  Updated Claude settings"
    else
        echo "  WARNING: jq not found, skipping settings.json update"
        echo "  Install jq (brew install jq) and re-run, or manually configure hooks"
    fi
else
    # Create new settings file
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    cat > "$SETTINGS_FILE" << EOF
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $HOOKS_DIR/user_prompt_submit.py",
            "timeout": 10
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $HOOKS_DIR/stop.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
EOF
    echo "  Created Claude settings"
fi

# Check for Ollama
echo ""
if command -v ollama >/dev/null 2>&1; then
    echo "Ollama found. Checking for phi3 model..."
    if ollama list 2>/dev/null | grep -q "phi3"; then
        echo "  phi3 model ready!"
    else
        echo "  phi3 model not found. Installing..."
        ollama pull phi3:3.8b
    fi
else
    echo "WARNING: Ollama not found!"
    echo "  Install: brew install ollama"
    echo "  Then run: ollama serve"
    echo "  And pull model: ollama pull phi3:3.8b"
fi

echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Restart Claude Code to pick up the new hooks"
echo "  2. Make sure Ollama is running (ollama serve)"
echo "  3. Summaries will appear in .claude/SUMMARY.txt after each response"
echo "  4. Run 'claude-summary' in any project for live streaming view"
echo ""
echo "Make sure $BIN_DIR is in your PATH:"
echo '  export PATH="$HOME/.local/bin:$PATH"'
