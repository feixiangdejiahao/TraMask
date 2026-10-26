cd /app/libs/core && cat > langchain_core/runnables/coalesce.py <<'PYEOF'
"""``Runnable`` that coalesces concurrent calls with identical inputs."""

from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, wait
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, overload

from typing_extensions import override

from langchain_core.runnables.base import RunnableBindingBase
from langchain_core.runnables.config import RunnableConfig, ensure_config, get_config_list
from langchain_core.runnables.utils import (
    Input,
    Output,
    gather_with_concurrency,
    gated_coro,
)

if TYPE_CHECKING:
    from langchain_core.callbacks.manager import (
        AsyncCallbackManagerForChainRun,
        CallbackManagerForChainRun,
    )

__all__ = ["CoalesceBackend", "CoalesceStats", "InMemoryCoalesceBackend"]


@dataclass(frozen=True)
class CoalesceStats:
    """Statistics about a coalescing backend."""

    active: int
    """Number of in-flight (not yet completed) unique executions."""

    coalesced: int
    """Cumulative number of calls that joined an in-flight execution."""

    total: int
    """Cumulative number of calls registered with the backend."""


def _canonical_key(key: Any) -> Any:
    """Produce a hashable key that is insensitive to dictionary key ordering.

    The coalescing key is based only on the input value. Dictionaries are
    canonicalized by sorting their items so that two dictionaries containing the
    same key/value pairs in different orders map to the same key.
    """
    if isinstance(key, dict):
        items = [(_canonical_key(k), _canonical_key(v)) for k, v in key.items()]
        items.sort(key=repr)
        return tuple(items)
    if isinstance(key, (list, tuple)):
        return tuple(_canonical_key(item) for item in key)
    if isinstance(key, (set, frozenset)):
        return frozenset(_canonical_key(item) for item in key)
    try:
        hash(key)
    except TypeError:
        # Fallback for unhashable custom objects. Using repr is deterministic for
        # immutable values; dicts/lists/tuples/sets are handled above.
        return ("__repr__", repr(key))
    return key


class _SyncWaiter:
    __slots__ = ("event", "result", "error", "cancelled")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None
        self.cancelled = False


class _AsyncWaiter:
    __slots__ = ("loop", "event", "result", "error", "cancelled")

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.event = asyncio.Event()
        self.result: Any = None
        self.error: BaseException | None = None
        self.cancelled = False


class _Execution:
    __slots__ = (
        "completed",
        "cancelled",
        "result",
        "error",
        "sync_waiters",
        "async_waiters",
    )

    def __init__(self) -> None:
        self.completed = False
        self.cancelled = False
        self.result: Any = None
        self.error: BaseException | None = None
        self.sync_waiters: list[_SyncWaiter] = []
        self.async_waiters: list[_AsyncWaiter] = []


class CoalesceBackend(ABC):
    """Backend that tracks in-flight executions for request coalescing.

    Implementations must be thread-safe: ``invoke`` may run in worker threads
    while ``ainvoke`` runs in an event loop, and the same backend is shared
    across both.
    """

    @abstractmethod
    def register(self, key: Any) -> bool:
        """Register interest in ``key``.

        Returns ``True`` if the caller is the first (leader) caller and should run
        the underlying execution. Returns ``False`` if another execution for the
        same key is already in flight and the caller should call :meth:`join`.
        """

    @abstractmethod
    def join(self, key: Any) -> Any:
        """Wait for the in-flight execution for ``key`` to finish and return its result.

        Raises the error produced by the execution, if any.
        """

    @abstractmethod
    def complete(
        self,
        key: Any,
        *,
        result: Any = None,
        error: BaseException | None = None,
    ) -> None:
        """Mark the execution for ``key`` as complete and wake any waiters."""

    @abstractmethod
    def is_active(self, key: Any) -> bool:
        """Return whether there is an in-flight execution for ``key``."""

    @property
    @abstractmethod
    def stats(self) -> CoalesceStats:
        """Return statistics about current and historical coalescing."""

    @abstractmethod
    async def aregister(self, key: Any) -> bool:
        """Async version of :meth:`register`."""

    @abstractmethod
    async def ajoin(self, key: Any) -> Any:
        """Async version of :meth:`join`."""

    @abstractmethod
    async def acomplete(
        self,
        key: Any,
        *,
        result: Any = None,
        error: BaseException | None = None,
    ) -> None:
        """Async version of :meth:`complete`."""

    @abstractmethod
    async def ais_active(self, key: Any) -> bool:
        """Async version of :meth:`is_active`."""

    def clear(self) -> None:
        """Cancel pending waiters and reset statistics.

        The default implementation is a no-op. Concrete backends may override it.
        """


class InMemoryCoalesceBackend(CoalesceBackend):
    """Thread-safe, in-memory :class:`CoalesceBackend` implementation."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._executions: dict[Any, _Execution] = {}
        self._active = 0
        self._coalesced = 0
        self._total = 0

    @override
    def register(self, key: Any) -> bool:
        ckey = _canonical_key(key)
        with self._lock:
            execution = self._executions.get(ckey)
            self._total += 1
            if execution is None or execution.completed or execution.cancelled:
                self._executions[ckey] = _Execution()
                self._active += 1
                return True
            self._coalesced += 1
            return False

    @override
    def join(self, key: Any) -> Any:
        ckey = _canonical_key(key)
        with self._lock:
            execution = self._executions.get(ckey)
            if execution is None:
                msg = f"No in-flight execution for key {key!r}."
                raise KeyError(msg)
            if execution.cancelled:
                raise asyncio.CancelledError()
            if execution.completed:
                if execution.error is not None:
                    raise execution.error
                return execution.result
            waiter = _SyncWaiter()
            execution.sync_waiters.append(waiter)

        waiter.event.wait()
        if waiter.cancelled:
            raise asyncio.CancelledError()
        if waiter.error is not None:
            raise waiter.error
        return waiter.result

    @override
    def complete(
        self,
        key: Any,
        *,
        result: Any = None,
        error: BaseException | None = None,
    ) -> None:
        ckey = _canonical_key(key)
        with self._lock:
            execution = self._executions.get(ckey)
            if execution is None or execution.completed or execution.cancelled:
                return
            execution.completed = True
            execution.result = result
            execution.error = error
            self._active -= 1
            sync_waiters = execution.sync_waiters
            async_waiters = execution.async_waiters
            execution.sync_waiters = []
            execution.async_waiters = []

        for waiter in sync_waiters:
            waiter.result = result
            waiter.error = error
            waiter.event.set()
        for waiter in async_waiters:
            waiter.result = result
            waiter.error = error
            waiter.loop.call_soon_threadsafe(waiter.event.set)

    @override
    def is_active(self, key: Any) -> bool:
        ckey = _canonical_key(key)
        with self._lock:
            execution = self._executions.get(ckey)
            return (
                execution is not None
                and not execution.completed
                and not execution.cancelled
            )

    @property
    @override
    def stats(self) -> CoalesceStats:
        with self._lock:
            return CoalesceStats(
                active=self._active,
                coalesced=self._coalesced,
                total=self._total,
            )

    @override
    async def aregister(self, key: Any) -> bool:
        return self.register(key)

    @override
    async def ajoin(self, key: Any) -> Any:
        ckey = _canonical_key(key)
        loop = asyncio.get_running_loop()
        with self._lock:
            execution = self._executions.get(ckey)
            if execution is None:
                msg = f"No in-flight execution for key {key!r}."
                raise KeyError(msg)
            if execution.cancelled:
                raise asyncio.CancelledError()
            if execution.completed:
                if execution.error is not None:
                    raise execution.error
                return execution.result
            waiter = _AsyncWaiter(loop)
            execution.async_waiters.append(waiter)

        await waiter.event.wait()
        if waiter.cancelled:
            raise asyncio.CancelledError()
        if waiter.error is not None:
            raise waiter.error
        return waiter.result

    @override
    async def acomplete(
        self,
        key: Any,
        *,
        result: Any = None,
        error: BaseException | None = None,
    ) -> None:
        self.complete(key, result=result, error=error)

    @override
    async def ais_active(self, key: Any) -> bool:
        return self.is_active(key)

    @override
    def clear(self) -> None:
        """Cancel all pending waiters and reset statistics."""
        with self._lock:
            for execution in self._executions.values():
                execution.cancelled = True
                for waiter in execution.sync_waiters:
                    waiter.cancelled = True
                    waiter.event.set()
                for waiter in execution.async_waiters:
                    waiter.cancelled = True
                    waiter.loop.call_soon_threadsafe(waiter.event.set)
                execution.sync_waiters = []
                execution.async_waiters = []
            self._executions.clear()
            self._active = 0
            self._coalesced = 0
            self._total = 0


class RunnableCoalesce(RunnableBindingBase[Input, Output]):  # type: ignore[no-redef]
    """``Runnable`` that coalesces concurrent calls with identical inputs.

    Only one execution runs per unique input while that input is in flight. All
    callers that arrive while it is running share the same result (or error).
    Once the execution completes, the next call with the same input runs fresh.
    """

    backend: CoalesceBackend
    """Backend used to track in-flight executions."""

    @classmethod
    @override
    def is_lc_serializable(cls) -> bool:
        return False

    def coalesce_info(self) -> CoalesceStats:
        """Return statistics about current coalescing state."""
        return self.backend.stats

    def coalesce_clear(self) -> None:
        """Cancel all pending waiters and reset coalescing statistics."""
        self.backend.clear()

    def _invoke(
        self,
        input_: Input,
        run_manager: "CallbackManagerForChainRun",
        config: RunnableConfig,
        **kwargs: Any,
    ) -> Output:
        if self.backend.register(input_):
            try:
                result = self.bound.invoke(input_, config, **kwargs)
            except BaseException as e:
                self.backend.complete(input_, error=e)
                raise
            self.backend.complete(input_, result=result)
            return result
        return self.backend.join(input_)

    @override
    def invoke(
        self,
        input: Input,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Output:
        return self._call_with_config(
            self._invoke, input, ensure_config(config), **kwargs
        )

    async def _ainvoke(
        self,
        input_: Input,
        run_manager: "AsyncCallbackManagerForChainRun",
        config: RunnableConfig,
        **kwargs: Any,
    ) -> Output:
        if await self.backend.aregister(input_):
            try:
                result = await self.bound.ainvoke(input_, config, **kwargs)
            except BaseException as e:
                await self.backend.acomplete(input_, error=e)
                raise
            await self.backend.acomplete(input_, result=result)
            return result
        return await self.backend.ajoin(input_)

    @override
    async def ainvoke(
        self,
        input: Input,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Output:
        return await self._acall_with_config(
            self._ainvoke, input, ensure_config(config), **kwargs
        )

    def _batch(
        self,
        inputs: list[Input],
        run_manager: list["CallbackManagerForChainRun"],
        config: list[RunnableConfig],
        **kwargs: Any,
    ) -> list[Output | Exception]:
        def run_one(input_: Input, cfg: RunnableConfig) -> Output | Exception:
            if self.backend.register(input_):
                try:
                    out: Output = self.bound.invoke(input_, cfg, **kwargs)
                except BaseException as e:
                    self.backend.complete(input_, error=e)
                    return e
                self.backend.complete(input_, result=out)
                return out
            else:
                try:
                    return self.backend.join(input_)
                except BaseException as e:
                    return e

        if len(inputs) == 1:
            return [run_one(inputs[0], config[0])]
        with get_config_list(config, len(inputs)) as _:  # noqa: F841
            pass
        # config is already a list of the right length; use it directly.
        with get_executor_for_config(config[0]) as executor:
            return cast(
                "list[Output | Exception]",
                list(executor.map(run_one, inputs, config)),
            )

    @override
    def batch(
        self,
        inputs: list[Input],
        config: RunnableConfig | list[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> list[Output]:
        return self._batch_with_config(
            self._batch,
            inputs,
            config,
            return_exceptions=return_exceptions,
            **kwargs,
        )

    async def _abatch(
        self,
        inputs: list[Input],
        run_manager: list["AsyncCallbackManagerForChainRun"],
        config: list[RunnableConfig],
        **kwargs: Any,
    ) -> list[Output | Exception]:
        async def run_one(input_: Input, cfg: RunnableConfig) -> Output | Exception:
            if await self.backend.aregister(input_):
                try:
                    out: Output = await self.bound.ainvoke(input_, cfg, **kwargs)
                except BaseException as e:
                    await self.backend.acomplete(input_, error=e)
                    return e
                await self.backend.acomplete(input_, result=out)
                return out
            else:
                try:
                    return await self.backend.ajoin(input_)
                except BaseException as e:
                    return e

        if len(inputs) == 1:
            return [await run_one(inputs[0], config[0])]
        return cast(
            "list[Output | Exception]",
            await gather_with_concurrency(
                config[0].get("max_concurrency"),
                *(run_one(i, cfg) for i, cfg in zip(inputs, config, strict=False)),
            ),
        )

    @override
    async def abatch(
        self,
        inputs: list[Input],
        config: RunnableConfig | list[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> list[Output]:
        return await self._abatch_with_config(
            self._abatch,
            inputs,
            config,
            return_exceptions=return_exceptions,
            **kwargs,
        )

    @overload
    def batch_as_completed(
        self,
        inputs: Sequence[Input],
        config: RunnableConfig | Sequence[RunnableConfig] | None = None,
        *,
        return_exceptions: Literal[False] = False,
        **kwargs: Any,
    ) -> Iterator[tuple[int, Output]]: ...

    @overload
    def batch_as_completed(
        self,
        inputs: Sequence[Input],
        config: RunnableConfig | Sequence[RunnableConfig] | None = None,
        *,
        return_exceptions: Literal[True],
        **kwargs: Any,
    ) -> Iterator[tuple[int, Output | Exception]]: ...

    @override
    def batch_as_completed(
        self,
        inputs: Sequence[Input],
        config: RunnableConfig | Sequence[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> Iterator[tuple[int, Output | Exception]]:
        if not inputs:
            return
        configs = get_config_list(config, len(inputs))
        index_keys: list[Any] = []
        groups: dict[Any, list[int]] = {}
        for i, input_ in enumerate(inputs):
            ckey = _canonical_key(input_)
            index_keys.append(ckey)
            groups.setdefault(ckey, []).append(i)
        pending = {ckey: len(indices) for ckey, indices in groups.items()}
        buffered: dict[Any, list[tuple[int, Output | Exception]]] = {}

        def run_one(
            i: int, input_: Input, cfg: RunnableConfig
        ) -> tuple[int, Output | Exception]:
            if return_exceptions:
                try:
                    return i, self.invoke(input_, cfg, **kwargs)
                except Exception as e:
                    return i, e
            return i, self.invoke(input_, cfg, **kwargs)

        if len(inputs) == 1:
            yield run_one(0, inputs[0], configs[0])
            return

        with get_executor_for_config(configs[0]) as executor:
            futures = {
                executor.submit(run_one, i, input_, cfg)
                for i, (input_, cfg) in enumerate(
                    zip(inputs, configs, strict=False)
                )
            }
            try:
                while futures:
                    done, futures = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        i, out = future.result()
                        ckey = index_keys[i]
                        buffered.setdefault(ckey, []).append((i, out))
                        pending[ckey] -= 1
                        if pending[ckey] == 0:
                            for item in buffered[ckey]:
                                yield item
                            buffered[ckey].clear()
            finally:
                for future in futures:
                    future.cancel()

    @overload
    def abatch_as_completed(
        self,
        inputs: Sequence[Input],
        config: RunnableConfig | Sequence[RunnableConfig] | None = None,
        *,
        return_exceptions: Literal[False] = False,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[int, Output]]: ...

    @overload
    def abatch_as_completed(
        self,
        inputs: Sequence[Input],
        config: RunnableConfig | Sequence[RunnableConfig] | None = None,
        *,
        return_exceptions: Literal[True],
        **kwargs: Any,
    ) -> AsyncIterator[tuple[int, Output | Exception]]: ...

    @override
    async def abatch_as_completed(
        self,
        inputs: Sequence[Input],
        config: RunnableConfig | Sequence[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[int, Output | Exception]]:
        if not inputs:
            return
        configs = get_config_list(config, len(inputs))
        index_keys: list[Any] = []
        groups: dict[Any, list[int]] = {}
        for i, input_ in enumerate(inputs):
            ckey = _canonical_key(input_)
            index_keys.append(ckey)
            groups.setdefault(ckey, []).append(i)
        pending = {ckey: len(indices) for ckey, indices in groups.items()}
        buffered: dict[Any, list[tuple[int, Output | Exception]]] = {}

        async def run_one(
            i: int, input_: Input, cfg: RunnableConfig
        ) -> tuple[int, Output | Exception]:
            if return_exceptions:
                try:
                    return i, await self.ainvoke(input_, cfg, **kwargs)
                except Exception as e:
                    return i, e
            return i, await self.ainvoke(input_, cfg, **kwargs)

        if len(inputs) == 1:
            yield await run_one(0, inputs[0], configs[0])
            return

        max_concurrency = configs[0].get("max_concurrency") if configs else None
        semaphore = asyncio.Semaphore(max_concurrency) if max_concurrency else None
        coros = [
            gated_coro(semaphore, run_one(i, input_, cfg))
            if semaphore
            else run_one(i, input_, cfg)
            for i, (input_, cfg) in enumerate(zip(inputs, configs, strict=False))
        ]
        for coro in asyncio.as_completed(coros):
            i, out = await coro
            ckey = index_keys[i]
            buffered.setdefault(ckey, []).append((i, out))
            pending[ckey] -= 1
            if pending[ckey] == 0:
                for item in buffered[ckey]:
                    yield item
                buffered[ckey].clear()

    def _stream_transformer(
        self,
        inputs: Iterator[Input],
        run_manager: "CallbackManagerForChainRun",
        config: RunnableConfig,
        **kwargs: Any,
    ) -> Iterator[Output]:
        input_ = next(inputs, None)
        if input_ is None:
            return
        if self.backend.register(input_):
            chunks: list[Output] = []
            try:
                for chunk in self.bound.stream(input_, config, **kwargs):
                    chunks.append(chunk)
                    yield chunk
            except GeneratorExit:
                raise
            except BaseException as e:
                self.backend.complete(input_, error=e)
                raise
            self.backend.complete(input_, result=chunks)
        else:
            result = self.backend.join(input_)
            for chunk in cast("list[Output]", result):
                yield chunk

    @override
    def stream(
        self,
        input: Input,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Iterator[Output]:
        yield from self._transform_stream_with_config(
            iter([input]),
            self._stream_transformer,
            ensure_config(config),
            **kwargs,
        )

    async def _astream_transformer(
        self,
        inputs: AsyncIterator[Input],
        run_manager: "AsyncCallbackManagerForChainRun",
        config: RunnableConfig,
        **kwargs: Any,
    ) -> AsyncIterator[Output]:
        input_ = await anext(inputs, None)
        if input_ is None:
            return
        if await self.backend.aregister(input_):
            chunks: list[Output] = []
            try:
                async for chunk in self.bound.astream(input_, config, **kwargs):
                    chunks.append(chunk)
                    yield chunk
            except GeneratorExit:
                raise
            except BaseException as e:
                await self.backend.acomplete(input_, error=e)
                raise
            await self.backend.acomplete(input_, result=chunks)
        else:
            result = await self.backend.ajoin(input_)
            for chunk in cast("list[Output]", result):
                yield chunk

    @override
    async def astream(
        self,
        input: Input,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Output]:
        async for chunk in self._atransform_stream_with_config(
            aiter([input]),
            self._astream_transformer,
            ensure_config(config),
            **kwargs,
        ):
            yield chunk
PYEOF
echo "written"