#!/bin/bash
# Wrapper to run stop.py as a true background process
# Redirects stdout/stderr so parent can exit immediately
# IMPORTANT: Keep stdin open - Claude Code passes hook data via stdin

# Read stdin into variable first (hook input data)
input_data=$(cat)

# Now background the process with stdout/stderr redirected
# Pass the input data via echo pipe
(echo "$input_data" | python3 /Users/joshuamullet/.claude/hooks/stop.py "$@" > /dev/null 2>&1) &

# Parent exits immediately
exit 0
