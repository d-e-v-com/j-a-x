# Procedure 001: Save Prompts

## Purpose
Log every prompt and response summary to maintain an audit trail.

## Steps
1. At session start, create or resume `prompts_history/YYYY-MM-DD_PROMPT_HISTORY.md`
2. For each user prompt, log:
   - Timestamp
   - Prompt summary (first line or key intent)
   - Response summary (what was done)
3. Commit prompt history at session end

## Format
```markdown
# Prompt History — YYYY-MM-DD

| # | Time | Prompt | Response Summary |
|---|------|--------|------------------|
| 1 | HH:MM | User prompt summary | What was done |
```
