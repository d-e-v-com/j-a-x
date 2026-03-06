# Ollama-Headless Usage Guide

## Interactive Chat
To start a session with a specific role:
```bash
ollama-headless-chat --role sysadmin
```

### v5 (Alpha) Features
- **Queueing:** You can type your next instruction while the model is still processing the previous one.
- **Micro-Boot:** Watch the system load roles and procedures line-by-line.
- **Boot Timer:** Performance is tracked in real-time.

## Policy Management
The security policy is defined in `scripts/ollama_headless/policy.yaml`.
- **Restricted (Default):** Strict allowlist for prod-safe operations.
- **Unrestricted:** Use `--unrestricted` in chat tools to bypass the allowlist (Safety Gate still blocks destructive commands).

## Command Line Runner
For non-interactive or one-off tasks:
```bash
python3 scripts/ollama_headless/ollama_headless.py --repo . --role sysadmin --prompt "Your task here"
```
This is the same engine used by `scripts/invoke_role.sh`.
