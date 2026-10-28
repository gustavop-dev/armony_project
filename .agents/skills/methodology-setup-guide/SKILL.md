---
name: methodology-setup-guide
description: "Reference guide for implementing the Memory Bank methodology system with Codex-compatible skills and AGENTS files in this repo."
---

# Methodology Setup Guide

Use `docs/claude-code-methodology-setup-guide.md` as the canonical long-form guide for the project's methodology system.

When applying that guide in Codex-compatible mode for this repository:
- Map root and scoped always-on instructions from `CLAUDE.md` files to the Codex compatibility layer exposed through `AGENTS.md`.
- Map versioned `.claude/skills/*` workflows to `.agents/skills/*`.
- Keep `docs/methodology/` and `tasks/` as the persistence layer for project memory.
- Keep `.codex/config.toml` aligned with the active project defaults.

If the user asks to initialize or refresh the methodology system, use the actual repo layout and current tracked files instead of inventing a generic structure.
