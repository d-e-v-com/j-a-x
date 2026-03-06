# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**JAX — AI Agent Client (Headless + Interactive Chat)**

JAX is a local AI agent runtime that runs against Ollama models. It supports:
- **Headless mode**: Autonomous agent loops for cron/automation (tool-calling, policy-guarded)
- **Chat mode**: Interactive terminal UI with tool support, streaming, and role-based missions

JAX was born from the `ollama-headless` framework built inside the RoboTrader AI-Admin system (Feb–Mar 2026). It has been carved out into its own project under the D-E-V.com organization.

### Owner
- **Company**: White Wolf Technology LLC, DBA D-E-V.com
- **GitHub Org**: d-e-v-com
- **Related Projects**: AIorg (parent company AI org management)

---

## Boot Sequence — READ AND FOLLOW ON EVERY SESSION START

On every new session, Claude MUST:

1. **Run `git pull`** to get the latest changes.
2. **Read all procedures** in `procedures/` and follow them throughout the session.
3. **Resume or create today's session state** per `procedures/002_PROCEDURE_save_session.md`.
4. **Resume or create today's prompt history** per `procedures/001_PROCEDURE_save_prompts.md`.
5. **Check `todos/`** for pending tasks to work on.
6. **Check `wip/`** for in-progress work to resume.
7. **Enter the work loop** per `procedures/005_PROCEDURE_agent_work_loop.md`.

---

## Folder Structure

```
j-a-x/
├── CLAUDE.md                 # Boot file for Claude Code (this file)
├── README.md                 # Project overview, install, usage
├── LICENSE                   # License (TBD)
├── .claude/
│   └── settings.json         # Project-level permissions
│
├── procedures/               # Numbered procedures Claude MUST follow
│   ├── 001_PROCEDURE_save_prompts.md
│   ├── 002_PROCEDURE_save_session.md
│   ├── 003_PROCEDURE_create_todo.md
│   ├── 004_PROCEDURE_commit_and_push.md
│   └── 005_PROCEDURE_agent_work_loop.md
│
├── sessions/                 # Daily session state (YYYY-MM-DD_SESSION_STATE.md)
├── prompts_history/          # Daily prompt logs
├── todos/                    # Pending tasks
│   └── DONE/                 # Completed tasks
├── wip/                      # Work in progress
│
├── src/                      # Source code
│   ├── jax_headless.py       # Headless agent runner (main engine)
│   ├── jax_chat.py           # Interactive chat client (latest stable)
│   ├── policy.yaml           # Default security policy (restricted)
│   ├── unrestricted_policy.yaml  # Unrestricted policy (debugging only)
│   ├── prompt_loader.py      # System prompt template loader
│   └── prompts/              # System prompt templates
│       ├── system_base.md    # Base identity + rules
│       ├── system_headless.md # Headless-specific rules
│       └── system_chat.md    # Chat-specific rules
│
├── legacy/                   # Full version history (v1–v6)
│   ├── chat-v1.py            # Original chat interface
│   ├── chat-v2.py            # v2 improvements
│   ├── chat-v3.py            # Stable top-down chat
│   ├── chat-v4.py            # Managed screen layout + side-by-side logic
│   ├── chat-v5.py            # Multi-threaded, non-blocking input queue
│   └── chat-v6.py            # Latest interactive version
│
├── scripts/
│   └── install.sh            # Install dependencies
│
├── docs/
│   ├── architecture/         # Architecture docs, diagrams
│   ├── versions/             # Per-version changelog
│   └── domains/              # Domain inventory
│
└── tests/                    # Tests
```

## Development

### Running JAX Headless
```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
python3 src/jax_headless.py --repo . --role sysadmin --model qwen3-coder --prompt "Your task here"
```

### Running JAX Chat
```bash
python3 src/jax_chat.py --role sysadmin
```

### Policy
- `src/policy.yaml` — restricted mode (default, cron-safe)
- `src/unrestricted_policy.yaml` — unrestricted mode (interactive debugging only)

## Testing

JAX requires Ollama running locally. Test on vmhost04 or physical host (not VMs without GPU/Ollama).

```bash
# Verify Ollama is reachable
curl -s http://127.0.0.1:11434/api/tags | python3 -m json.tool

# Run headless test
python3 src/jax_headless.py --repo . --role sysadmin --model qwen3-coder --prompt "Run git status and report"
```

## Todo Lifecycle

```
todos/       pending tasks, not yet started
wip/         actively being worked on
todos/DONE/  completed tasks (moved here as-is, never renamed)
```

## Provenance

This code was carved out from:
- **Source repo**: `RoboTrader-io/Ai-admin` (private)
- **Source paths**: `scripts/ollama_headless/`, `scripts/ollama-headless-chat-v*.py`, `docs/frameworks/ollama-headless/`
- **Commit range**: Feb 27 – Mar 6, 2026 (~30 commits across chat v1–v6 and headless runner)
- **Original name**: ollama-headless
