cd /app && git config user.email "dev@example.com" && git config user.name "Developer" && git commit -m "feat(core): add Runnable.with_coalesce for request coalescing

Add a with_coalesce method to Runnable that wraps it with request
coalescing. When multiple callers invoke with the same input
concurrently, only one underlying execution runs and all callers receive
the same result (or error).

New types CoalesceBackend, CoalesceStats, and InMemoryCoalesceBackend
live in langchain_core.runnables.coalesce and are exported from
langchain_core.runnables. The InMemory backend is thread-safe and
supports both synchronous and asynchronous waiting.

Coalescing applies to sync/async invoke, stream, batch, and
batch-as-completed, while transform, atransform, and event streaming
pass through transparently. Batch methods coalesce per item and preserve
positional order; batch-as-completed yields coalesced duplicates
consecutively. Joined callers fire chain-start and chain-end callbacks.
The wrapper exposes coalesce_info() and coalesce_clear()." && git log --oneline -3 && git status