#!/usr/bin/env bash
# PreToolUse guard: reject `git add -A` / `git add .` / `git add --all`.
#
# CLAUDE.md forbids these in this repo — one slip stages `.env`,
# `data/raw/*.csv`, or `transform/target/`. Files must be staged by name.
#
# Reads the Claude Code PreToolUse payload on stdin (Bash matcher), inspects
# tool_input.command, and denies the call if it contains a blanket `git add`.
set -euo pipefail

payload="$(cat)"
cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null || true)"

# Collapse whitespace so multi-space / newline forms still match.
norm="$(printf '%s' "$cmd" | tr -s '[:space:]' ' ')"

# Match `git add` whose args include a blanket selector (-A, --all, or a bare
# `.`), allowing other args before it but never crossing a command separator.
# The `.` alternative requires a trailing space/end so `git add ./path` is OK.
if printf '%s' "$norm" | grep -Eq 'git[[:space:]]+add([[:space:]]+[^;|&]*)?[[:space:]](-A|--all|\.)([[:space:]]|$)'; then
  jq -n --arg r "Blocked: 'git add -A' / 'git add .' / 'git add --all' are forbidden in this repo (CLAUDE.md) — they can stage .env, data/raw/*.csv, or transform/target/. Stage files explicitly by name: git add path/to/file ..." \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
fi

exit 0
