# Claude Summary Hooks

Session summary generation hooks for Claude Code CLI.

## Installation

### Option 1: Direct Python execution (simpler, but blocks for ~40-60s)

Configure in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 /path/to/hooks/stop.py",
            "timeout": 90
          }
        ]
      }
    ]
  }
}
```

### Option 2: Shell wrapper (recommended - non-blocking)

Use the shell wrapper for truly non-blocking background execution:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/hooks/stop-wrapper.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

**Why use the wrapper?**
- Hook exits instantly (~5ms) - doesn't block Claude Code
- Summary generation runs in background (~40-60s)
- Properly redirects stdout/stderr so parent process can exit
- Preserves stdin for hook data

## How It Works

### stop.py
- Receives hook data via stdin (session_id, transcript_path, cwd)
- Immediately writes session file (marks as "waiting")
- Forks a background process for summary generation
- Parent exits in ~20ms (hook completes instantly)
- Child process:
  - Reads conversation history
  - Creates PTY and spawns `claude -p` with session detachment
  - Prevents `/dev/tty` blocking issues (GitHub Issue #13598)
  - Generates summary using Claude Haiku (~40-60s)
  - Strips ANSI escape codes from PTY output
  - Writes clean summary to `.claude/SUMMARY.txt`
  - Updates session file with summary

### stop-wrapper.sh
- Reads stdin (hook data) synchronously
- Backgrounds the Python process with stdout/stderr redirected
- Exits immediately so Claude Code doesn't wait
- Ensures summary generation runs independently

### user_prompt_submit.py
- Captures user prompts as they're submitted
- Builds conversation history for summary generation
- Trims to last MAX_EXCHANGES exchanges to prevent unbounded growth

## Key Features

### Recursive Hook Prevention
Uses `CLAUDE_HOOK_SKIP=1` environment variable to prevent hooks from triggering during nested `claude -p` calls.

### PTY-based Execution
- Creates pseudo-terminal pair for `claude -p` subprocess
- Uses `start_new_session=True` to detach from controlling terminal
- Prevents Claude from opening `/dev/tty` and blocking
- 90-second timeout (claude -p takes 40-50s even for simple prompts)

### ANSI Escape Code Cleaning
Two-pass approach to strip terminal control codes from PTY output:
1. Strip full ANSI sequences (ESC-based)
2. Strip trailing terminal garbage lines (e.g., `9;4;0;\x07`)

Result: Clean JSON output without corrupted escape sequences

## Debugging

Debug logs are written to:
- `/tmp/claude-debug-stop.log` - stop.py execution details
- `/tmp/claude-debug-user-prompt.log` - user_prompt_submit.py details

Check logs for timing information:
```bash
tail -50 /tmp/claude-debug-stop.log
```

## Performance

With shell wrapper:
- Hook execution: ~5ms (instant)
- Summary generation: ~40-60s (background)
- No blocking of Claude Code interaction

Without wrapper:
- Hook execution: ~40-60s (blocks Claude Code)
- Summary generation: ~40-60s (foreground)

## Known Issues

### Claude CLI Latency
`claude -p` takes 40-50+ seconds even for simple prompts due to API initialization overhead. This is not a bug in the hooks - it's the nature of spawning a fresh Claude Code session.

### GitHub Issues Referenced
- [#13598](https://github.com/anthropics/claude-code/issues/13598) - Claude opens /dev/tty directly causing hangs
- [#9026](https://github.com/anthropics/claude-code/issues/9026) - Claude -p hangs without TTY

## Requirements

- Python 3.6+
- Claude Code CLI installed and in PATH
- Bash shell (for wrapper script)

## License

MIT
