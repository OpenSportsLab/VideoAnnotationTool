# Question/Answer Controller

## Role
Owns Question/Answer mode behavior:
- per-sample grouped question/answer editing with autosave
- emits typed mutation intents to `HistoryManager`

## Contracts
- Constructor accepts only panel dependency.
- Does not mutate dataset directly.
- Uses grouped `answers` payloads (`question`, `answers[]`) with non-empty answers only.
