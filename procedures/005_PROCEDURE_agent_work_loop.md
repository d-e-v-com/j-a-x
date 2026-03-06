# Procedure 005: Agent Work Loop

## Purpose
Ensure continuous work — never stop without checking for the next task.

## Core Rule
**Never stop. When you finish a task, immediately check for the next one.**

## The Work Loop

1. **Check wip/** — any items that need continuation? Resume them.
2. **Check todos/** — any PENDING todos that are unblocked? Pick highest priority, move to wip/, start work.
3. **Explore and learn** — if no assigned work, explore the codebase, write tests, improve docs, identify gaps, create TODOs.
4. **Report status** — update session state.

## Priority Order
1. Items in wip/ that need continuation
2. Unblocked todos (lowest ID first)
3. Proactive work (tests, docs, refactoring)
