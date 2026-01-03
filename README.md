# Claude Summary Hooks

Automatically generates 2-line summaries of your Claude Code sessions using a local LLM (Ollama). Helps you track what you accomplished across coding sessions.

## What it does

1. Captures your prompts and Claude's responses
2. Reads project context (CLAUDE.md, PLAN.md)
3. Uses local Phi-3 model to generate a summary
4. Saves to `.claude/SUMMARY.txt` in your project

## Requirements

- Claude Code 2.0+
- Ollama running locally
- phi3:3.8b model

## Installation

```bash
# Clone the repo
git clone https://github.com/joshua-mullet-town/claude-summary-hooks.git ~/code/claude-summary-hooks

# Run the installer
~/code/claude-summary-hooks/install.sh

# Make sure Ollama is running
ollama serve

# Pull the model if not already installed
ollama pull phi3:3.8b
```

## Usage

After installation, summaries are automatically generated after each Claude Code response.

View summaries:
```bash
# Live streaming view (like tail -f)
claude-summary

# Or just read the file
cat .claude/SUMMARY.txt
```

## Example Output

```
USER asked help implementing user authentication with JWT tokens.
AGENT created JWT auth system with login/signup routes, middleware, and token validation.
```

## Uninstall

```bash
~/code/claude-summary-hooks/uninstall.sh
```

## Privacy

Completely private - uses local Ollama, no data sent to cloud services.
