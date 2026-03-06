# Procedure 004: Commit and Push

## Purpose
Standards for git commits in this project.

## Commit Message Format
```
<scope>: <concise description>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

### Scope Examples
- `core:` — changes to jax_headless.py or jax_chat.py
- `policy:` — security policy changes
- `docs:` — documentation changes
- `procedures:` — procedure changes
- `tests:` — test changes
- `legacy:` — legacy version updates

## Rules
- Commit after completing meaningful work units
- Never commit secrets, credentials, or API keys
- Always `git pull` before pushing to avoid conflicts
- Use specific file adds (not `git add -A`) to avoid accidental inclusions
