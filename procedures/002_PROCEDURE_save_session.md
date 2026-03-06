# Procedure 002: Save Session State

## Purpose
Maintain daily session state for continuity across sessions.

## Steps
1. At session start, create or resume `sessions/YYYY-MM-DD_SESSION_STATE.md`
2. Track:
   - Status (ACTIVE / IDLE / CLOSED)
   - Goals for the session
   - Work log (what was done, files touched, outcome)
   - Decisions made
   - Blockers encountered
   - Open questions
3. Update throughout the session
4. At session end, mark status and commit

## Format
```markdown
# Session State — YYYY-MM-DD

## Status: ACTIVE

## Goals
- Goal 1
- Goal 2

## Work Log
| # | What was done | Files touched | Outcome |
|---|---------------|---------------|---------|
| 1 | Description | file.py | Result |

## Decisions Made
- Decision 1

## Blockers
| Blocker | Waiting On | Since |
|---------|-----------|-------|
| Description | Who/what | Date |
```
