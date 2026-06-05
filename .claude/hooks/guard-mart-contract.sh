#!/usr/bin/env bash
# PreToolUse guard for the mart_recovery_state public-API contract.
#
# mart_recovery_state has TWO downstream consumers (the weekly-health-review
# Claude skill + scripts/push_recovery_state.py Firestore feed). CLAUDE.md
# marks the model file off-limits and the marts schema.yml as the durable
# contract-test surface. This hook turns those prose rules into a gate.
#
# Reads the Claude Code PreToolUse payload on stdin (Edit|Write|MultiEdit),
# inspects the target file path, and returns a permission decision:
#   - deny  : direct edits to mart_recovery_state.sql (off-limits model)
#   - ask   : edits to transform/models/marts/schema.yml (holds the tests)
#   - allow : everything else (silent exit 0)
set -euo pipefail

payload="$(cat)"

# Target path lives at tool_input.file_path for Edit/Write/MultiEdit.
fp="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"

emit() { # $1=decision  $2=reason
  jq -n --arg d "$1" --arg r "$2" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:$d,permissionDecisionReason:$r}}'
  exit 0
}

case "$fp" in
  */transform/models/marts/mart_recovery_state.sql)
    emit deny "mart_recovery_state is a public API with TWO downstream consumers (weekly-health-review skill + scripts/push_recovery_state.py Firestore feed). CLAUDE.md marks this file off-limits. To change the contract, update BOTH consumers in lockstep and keep the dbt accepted_values(recovery_signal) + unique(day) tests. With explicit authorization, edit .claude/settings.json to bypass this guard."
    ;;
  */transform/models/marts/schema.yml)
    emit ask "marts/schema.yml holds the mart_recovery_state contract tests (accepted_values on recovery_signal, unique on day) — the durable contract surface for both downstream consumers. Confirm this edit does NOT weaken or remove them."
    ;;
esac

# Default: allow silently.
exit 0
