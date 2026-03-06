# Ollama-Headless Framework

The **Ollama-Headless** framework is a local, autonomous agent execution environment designed for the AI-Admin organization. It enables roles like `sysadmin`, `python-dev`, and `auditor` to operate without dependency on proprietary cloud models.

## Core Philosophies
1. **Local Independence:** All inference runs on `127.0.0.1:11434` using Ollama.
2. **Mission-First Architecture:** Agents start with a rigid "Mission Manifest" containing their identity and procedures.
3. **Hybrid Tooling:** Supports both native API tool-calling and fallback markdown parsing for older/smaller models.
4. **Interactive Transparency:** Real-time visibility into the "Agent Logic" via high-fidelity terminal UIs.

## Version Lineage
- **v3 (Legacy Stable):** Reliable top-down chat interface.
- **v4 (Flagship):** Managed screen layout with sticky footer and side-by-side logic.
- **v5 (Next-Gen Alpha):** Multi-threaded, non-blocking input queue with Linux-style micro-boot context injection.

## Project Structure
- `scripts/ollama_headless/ollama_headless.py`: The core headless runner used by cron.
- `scripts/ollama_headless/policy.yaml`: The command allowlist and security policy.
- `scripts/ollama-headless-chat-v*.py`: Interactive chat tools.
- `scripts/invoke_role.sh`: The integration point for the organization's cron system.
