cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/base.py'
s = open(p).read()
anchor = '    """ --- Helper methods for Subclasses --- """'
method = '''    def with_coalesce(
        self,
        *,
        backend: CoalesceBackend | None = None,
    ) -> Runnable[Input, Output]:
        """Create a new `Runnable` that coalesces concurrent calls with identical inputs.

        When multiple callers invoke the returned `Runnable` with the same input
        concurrently, only one underlying execution runs and all callers receive the
        same result (or error). Coalescing applies to sync and async `invoke`,
        `stream`, `batch`, and `batch_as_completed`, sharing one backend so in-flight
        state is visible across methods.

        Args:
            backend: The coalescing backend to use. If `None`, a new
                `InMemoryCoalesceBackend` is created. Backends can be shared between
                multiple wrappers to coalesce across them.

        Returns:
            A new `Runnable` that coalesces concurrent calls.

        Example:
            ```python
            from langchain_core.runnables import RunnableLambda

            runnable = RunnableLambda(lambda x: expensive(x)).with_coalesce()

            # Concurrent calls with the same input run the underlying function once.
            ```
        """
        # Import locally to prevent circular import
        from langchain_core.runnables.coalesce import (  # noqa: PLC0415
            InMemoryCoalesceBackend,
            RunnableCoalesce,
        )

        if backend is None:
            backend = InMemoryCoalesceBackend()
        return RunnableCoalesce(bound=self, backend=backend)

'''
assert anchor in s
s = s.replace(anchor, method + anchor, 1)
# Add CoalesceBackend to TYPE_CHECKING
old_tc = "    from langchain_core.runnables.fallbacks import (\n        RunnableWithFallbacks as RunnableWithFallbacksT,\n    )"
new_tc = "    from langchain_core.runnables.coalesce import CoalesceBackend\n    from langchain_core.runnables.fallbacks import (\n        RunnableWithFallbacks as RunnableWithFallbacksT,\n    )"
assert old_tc in s
s = s.replace(old_tc, new_tc, 1)
open(p, 'w').write(s)
print("done")
PY
grep -n "with_coalesce\|CoalesceBackend" langchain_core/runnables/base.py | head