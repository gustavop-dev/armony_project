#!/usr/bin/env bash
# Hook SessionStart: equivalente local del session-start-git-status.sh del fleet.
# Solo lectura: fetch (si hay remoto) + status. Imprime la línea que espera el
# Session Start Protocol de CLAUDE.md/AGENTS.md.
set -u
top=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
repo=$(basename "$(dirname "$common")")
branch=$(git branch --show-current 2>/dev/null)
[ -n "$branch" ] || branch="(detached)"

if [ -n "$(git remote 2>/dev/null)" ]; then
  timeout 10 git fetch --quiet 2>/dev/null || true
fi
behind=0; ahead=0
if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  read -r behind ahead < <(git rev-list --left-right --count '@{u}...HEAD' 2>/dev/null)
fi
dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

if [ "$(git rev-parse --absolute-git-dir)" = "$common" ]; then
  tree=main-clone
else
  tree="worktree:$(basename "$top")"
fi
echo "[session-start] $repo @ $branch | behind=$behind ahead=$ahead dirty=$dirty | tree=$tree"
