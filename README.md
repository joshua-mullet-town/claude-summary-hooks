# Claude Summary Hooks

Automatically generates concise summaries of your Claude Code sessions. Helps you track what you accomplished across coding sessions and powers Whisper Village session dots.

## What it does

1. Captures your prompts and Claude's responses
2. Reads project context (CLAUDE.md, PLAN.md)
3. Uses Claude Haiku to generate a brief summary
4. Saves to `.claude/SUMMARY.txt` in your project
5. Writes session state to `~/.claude/sessions/` for Whisper Village

## Requirements

- Claude Code CLI (installed and in PATH)
- Python 3
- jq (`brew install jq`)

## Installation

```bash
# Clone the repo (first time only)
git clone https://github.com/joshua-mullet-town/claude-summary-hooks.git ~/code/claude-summary-hooks

# Run the installer (auto-pulls latest from GitHub)
~/code/claude-summary-hooks/install.sh
```

Re-running `install.sh` always pulls the latest version first, so you never need to manually `git pull`.

## Usage

After installation, summaries are automatically generated after each Claude Code session.

View summaries:
```bash
# Live streaming view (like tail -f)
claude-summary

# Or just read the file
cat .claude/SUMMARY.txt
```

## Example Output

```json
{"user_summary": "Add dark mode toggle", "agent_summary": "Implemented theme switcher in settings"}
```

## Uninstall

```bash
~/code/claude-summary-hooks/uninstall.sh
```

## How it works

- **UserPromptSubmit hook**: Captures each user prompt, tracks session status as "working"
- **Stop hook**: After Claude responds, generates a summary via `claude -p --model haiku`
- Python path is resolved at install time (handles pyenv/homebrew/system python)
- Claude CLI is discovered at runtime (checks PATH + common install locations)
