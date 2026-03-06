# JAX — AI Agent Client

**JAX** is a local AI agent runtime powered by [Ollama](https://ollama.ai). It runs autonomous agent loops (headless) and interactive chat sessions with tool-calling, security policies, and role-based missions.

## Features

- **Headless Mode** — Autonomous agent loops for cron/automation. Tool-calling with YAML-based security policy. Designed for unattended operation.
- **Interactive Chat** — Rich terminal UI with streaming, tool execution, and real-time agent logic visibility. Multiple UI generations (v1–v6).
- **Security Policy** — YAML allowlist/denylist for command execution. Restricted mode for production, unrestricted for debugging.
- **Role-Based Missions** — Agents boot with role identity and mission context. Supports any role definition.
- **Hybrid Tool Extraction** — Native Ollama tool-calling + markdown fallback parsing for models that don't support structured tool use.
- **Audit Trail** — JSONL logging of all tool executions.

## Quick Start

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.ai) running locally
- A pulled model (e.g., `ollama pull qwen3-coder`)

### Headless (Automation)
```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
python3 src/jax_headless.py \
  --repo . \
  --role sysadmin \
  --model qwen3-coder \
  --prompt "Read the repo and find work to do"
```

### Interactive Chat
```bash
python3 src/jax_chat.py --role sysadmin
```

## Project Structure

```
src/
  jax_headless.py           # Headless agent runner (main engine)
  jax_chat.py               # Interactive chat (latest stable, v6-based)
  policy.yaml               # Restricted security policy (default)
  unrestricted_policy.yaml  # Unrestricted policy (debugging only)
  prompt_loader.py          # System prompt loader
  prompts/                  # System prompt templates

legacy/                     # Full version history (v1–v6 chat clients)
docs/                       # Architecture, version history, domains
```

## Security Policy

JAX enforces command execution via YAML policy files:

**Restricted (default):**
- Strict allowlist: `ls`, `cat`, `grep`, `find`, `git` commands, `python`, `pytest`
- Hard deny: `sudo`, `rm -rf`, `curl`, `wget`, `../`

**Unrestricted:**
- All commands allowed except destructive system commands (`sudo`, `mkfs`, `dd`, `reboot`, `shutdown`)

## Version History

| Version | Codename | Key Feature |
|---------|----------|-------------|
| v1 | Original | Basic chat interface |
| v2 | — | Improvements |
| v3 | Legacy Stable | Reliable top-down chat, streaming, persistent history |
| v4 | Flagship | Managed screen layout, sticky footer, side-by-side agent logic |
| v5 | Next-Gen Alpha | Multi-threaded, non-blocking input queue, micro-boot context |
| v6 | Latest | Current development version |
| Headless | Production | Cron-safe autonomous runner with policy guard |

## Origin

JAX was originally built as `ollama-headless` inside the [RoboTrader AI-Admin](https://github.com/RoboTrader-io/Ai-admin) multi-agent autonomous system during Feb–Mar 2026. It has been carved out into its own project for independent development and broader use.

## License

TBD

## Organization

- **Company**: White Wolf Technology LLC, DBA [D-E-V.com](https://d-e-v.com)
- **GitHub**: [d-e-v-com](https://github.com/d-e-v-com)
