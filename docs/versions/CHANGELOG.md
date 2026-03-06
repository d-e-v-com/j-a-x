# JAX Version History

## Origin

JAX was originally developed as `ollama-headless` inside the RoboTrader AI-Admin multi-agent system
(`RoboTrader-io/Ai-admin`) during February–March 2026.

The code was carved out into this standalone repo on 2026-03-06.

## Version Lineage

### Headless Runner (jax_headless.py)
- Built as `ollama_headless.py` for cron-invoked autonomous agent loops
- Tool-calling against Ollama `/api/chat` API
- YAML policy enforcement (restricted + unrestricted modes)
- Hybrid tool extraction (native API + markdown fallback)
- JSONL audit trail logging
- Key bug fixes by python-dev: grep_search glob param, git_commit quoting

### Chat v1 (legacy/chat-v1.py)
- Original interactive chat interface
- Basic prompt/response loop

### Chat v2 (legacy/chat-v2.py)
- Improvements over v1

### Chat v3 (legacy/chat-v3.py) — "Legacy Stable"
- Real-time streaming
- Persistent chat history
- Graceful Ctrl+C handling
- Optimized 32k context
- Stable top-down chat interface

### Chat v4 (legacy/chat-v4.py) — "Flagship"
- Managed screen layout with curses
- Sticky footer prompt
- Side-by-side Agent Logic panel
- Live spinner animation
- Mission context framing
- Interactive boot log

### Chat v5 (legacy/chat-v5.py) — "Next-Gen Alpha"
- Multi-threaded architecture
- Non-blocking input queue
- Background task worker
- Linux-style micro-boot context injection
- Boot timer performance tracking

### Chat v6 (legacy/chat-v6.py, src/jax_chat.py) — "Latest"
- Current development version
- Basis for jax_chat.py

## Key Commits (from Ai-admin repo)
- v3.3.0–v3.6.0: Streaming, history, graceful shutdown, logic loop fix
- v4.0.0–v4.6.1: Screen management, sticky UI, boot manifest, spinner fix
- v5.0.0–v5.4.0: Multi-threaded async, non-blocking queue, stable UI
- v6 WIP: Latest interactive version
- Headless: Continuous evolution alongside chat versions
