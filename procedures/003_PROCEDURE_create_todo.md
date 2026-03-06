# Procedure 003: Create and Manage Todos

## Purpose
Track all tasks using a file-based system with clear lifecycle stages.

## Todo Lifecycle
```
todos/  ->  wip/  ->  todos/DONE/
(pending)  (active)  (completed)
```

## Creating a Todo

1. Determine the next sequential number (check todos/, wip/, todos/DONE/)
2. Create `todos/NNN_TODO_short_description.md`:

```markdown
# TODO-NNN: Short Description

## Status: PENDING
## Created: YYYY-MM-DD
## Priority: HIGH | MEDIUM | LOW

## Description
What needs to be done.

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## History
- YYYY-MM-DD: Created
```

## Starting Work
1. Move file from `todos/` to `wip/` (no rename)
2. Update Status to `IN PROGRESS`
3. Add history entry

## Completing a Todo
1. Check off all acceptance criteria
2. Update Status to `DONE`
3. Move file from `wip/` to `todos/DONE/` (no rename)

## Rules
- Never rename files when moving between folders
- Numbers are global and never reused
- WIP items may span multiple sessions
