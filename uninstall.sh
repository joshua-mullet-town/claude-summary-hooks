#!/bin/bash
#
# claude-summary-hooks uninstaller
# Removes Claude Code hooks for session summary generation
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$HOME/.claude/hooks"
SETTINGS_FILE="$HOME/.claude/settings.json"
BIN_DIR="$HOME/.local/bin"

# Pull latest from GitHub before uninstalling (ensures correct cleanup logic)
if [ -d "$SCRIPT_DIR/.git" ]; then
    echo "Pulling latest version from GitHub..."
    (cd "$SCRIPT_DIR" && git pull --ff-only 2>/dev/null) && echo "  Updated to latest version" || echo "  (already up to date or offline)"
fi

echo "Uninstalling claude-summary-hooks..."

# Remove hook files
rm -f "$HOOKS_DIR/user_prompt_submit.py"
rm -f "$HOOKS_DIR/stop.py"
echo "  Removed hooks from $HOOKS_DIR"

# Remove the claude-summary command
rm -f "$BIN_DIR/claude-summary"
echo "  Removed claude-summary from $BIN_DIR"

# Update Claude settings.json
if [ -f "$SETTINGS_FILE" ] && command -v jq >/dev/null 2>&1; then
    TEMP_FILE=$(mktemp)

    # Remove our UserPromptSubmit hook
    jq 'del(.hooks.UserPromptSubmit[] | select(.hooks[]?.command | contains("user_prompt_submit.py")))' "$SETTINGS_FILE" > "$TEMP_FILE"

    # Remove our Stop hook
    jq 'del(.hooks.Stop[] | select(.hooks[]?.command | contains("stop.py")))' "$TEMP_FILE" > "${TEMP_FILE}.2"

    # Clean up empty arrays
    jq '
        if .hooks.UserPromptSubmit == [] then del(.hooks.UserPromptSubmit) else . end |
        if .hooks.Stop == [] then del(.hooks.Stop) else . end |
        if .hooks == {} then del(.hooks) else . end
    ' "${TEMP_FILE}.2" > "$SETTINGS_FILE"

    rm -f "$TEMP_FILE" "${TEMP_FILE}.2"
    echo "  Updated Claude settings"
fi

echo ""
echo "Uninstallation complete!"
echo "Note: Existing .claude/SUMMARY.txt files in projects were not removed."
