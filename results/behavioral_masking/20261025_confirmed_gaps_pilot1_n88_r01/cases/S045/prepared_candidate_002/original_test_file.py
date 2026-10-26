"""Tests for Runnable.with_coalesce and coalescing backends."""

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Iterator

import pytest

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import (
    InMemoryCoalesceBackend,
    Runnable,
    RunnableLambda,
    RunnablePassthrough,
)
from langchain_core.runnables.coalesce import CoalesceBackend, CoalesceStats


def test_exports() -> None:
    from langchain_core.runnables import (  # noqa: PLC0415
        CoalesceBackend as ExportedBackend,
        CoalesceStats as ExportedStats,
        InMemoryCoalesceBackend as ExportedMemoryBackend,
    )

    assert ExportedBackend is CoalesceBackend
    assert ExportedStats is CoalesceStats
    assert ExportedMemoryBackend is InMemoryCoalesceBackend
    assert hasattr(Runnable, "with_coalesce")


async def test_async_invoke_coalesces() -> None:
    calls: list[int] = []

    async def slow(x: int) -> int:
        await asyncio.sleep(0.1)
        calls.append(x)
        return x * 2

    runnable = RunnableLambda(slow).with_coalesce()
    results = await asyncio.gather(
        runnable.ainvoke(5), runnable.ainvoke(5), runnable.ainvoke(5)
    )
    assert results == [10, 10, 10]
    assert len(calls) == 1
    assert runnable.coalesce_info() == CoalesceStats(active=0, coalesced=2, total=3)


def test_sync_invoke_coalesces() -> None:
    calls: list[int] = []
    lock = threading.Lock()

    def slow(x: int) -> int:
        time.sleep(0.1)
        with lock:
            calls.append(x)
        return x * 2

    runnable = RunnableLambda(slow).with_coalesce()
    results: list[int] = []

    def invoke() -> None:
        results.append(runnable.invoke(7))

    threads = [threading.Thread(target=invoke) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [14, 14, 14]
    assert len(calls) == 1


async def test_dict_key_ordering() -> None:
    calls: list[dict] = []

    def f(d: dict) -> int:
        calls.append(d)
        return sum(d.values())

    runnable = RunnableLambda(f).with_coalesce()
    out = await asyncio.gather(
        runnable.ainvoke({"a": 1, "b": 2}),
        runnable.ainvoke({"b": 2, "a": 1}),
    )
    assert out == [3, 3]
    assert len(calls) == 1


def test_fresh_after_complete() -> None:
    calls: list[int] = []

    def f(x: int) -> int:
        calls.append(x)
        return x

    runnable = RunnableLambda(f).with_coalesce()
    assert runnable.invoke(1) == 1
    assert runnable.invoke(1) == 1
    assert len(calls) == 2


def test_stream_join_replays_all_chunks() -> None:
    async def gen(x: int) -> AsyncIterator[str]:
        yield "a"
        await asyncio.sleep(0.05)
        yield "b"
        yield "c"

    runnable = RunnableLambda(gen).with_coalesce()

    async def main() -> tuple[list[str], list[str]]:
        leader = runnable.astream(1)
        joiner = runnable.astream(1)
        first_leader = await anext(leader)
        await asyncio.sleep(0.05)
        joiner_first = asyncio.create_task(anext(joiner))
        await asyncio.sleep(0.05)
        leader_rest = [chunk async for chunk in leader]
        first_joiner = await joiner_first
        joiner_rest = [chunk async for chunk in joiner]
        return [first_leader, *leader_rest], [first_joiner, *joiner_rest]

    leader_chunks, joiner_chunks = asyncio.run(main())
    assert leader_chunks == ["a", "b", "c"]
    assert joiner_chunks == ["a", "b", "c"]


def test_batch_coalesces_per_item() -> None:
    calls: list[int] = []

    def f(x: int) -> int:
        time.sleep(0.1)
        calls.append(x)
        return x + 1

    runnable = RunnableLambda(f).with_coalesce()
    out = runnable.batch([1, 2, 1, 1, 2])
    assert out == [2, 3, 2, 2, 3]
    assert sorted(calls) == [1, 2]


def test_batch_as_completed_duplicates_consecutive() -> None:
    calls: list[int] = []

    def f(x: int) -> int:
        time.sleep(0.1 * (x % 2))
        calls.append(x)
        return x * 10

    runnable = RunnableLambda(f).with_coalesce()
    results = list(runnable.batch_as_completed([1, 1, 2]))
    indices = [i for i, _ in results]
    assert sorted(indices) == [0, 1, 2]
    assert calls.count(1) == 1
    assert abs(indices.index(0) - indices.index(1)) == 1


class CountingHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        self.starts = 0
        self.ends = 0

    def on_chain_start(self, *args: object, **kwargs: object) -> None:
        self.starts += 1

    def on_chain_end(self, *args: object, **kwargs: object) -> None:
        self.ends += 1


def test_joined_callers_fire_callbacks() -> None:
    async def f(x: int) -> int:
        await asyncio.sleep(0.1)
        return x

    runnable = RunnableLambda(f).with_coalesce()
    leader_handler = CountingHandler()
    joiner_handler = CountingHandler()

    async def main() -> None:
        await asyncio.gather(
            runnable.ainvoke(1, {"callbacks": [leader_handler]}),
            runnable.ainvoke(1, {"callbacks": [joiner_handler]}),
        )

    asyncio.run(main())
    assert joiner_handler.starts == 1
    assert joiner_handler.ends == 1
    assert leader_handler.starts >= 1
    assert leader_handler.ends >= 1


async def test_error_propagates_to_all() -> None:
    def f(x: int) -> int:
        raise ValueError("boom")

    runnable = RunnableLambda(f).with_coalesce()
    results = await asyncio.gather(
        runnable.ainvoke(1), runnable.ainvoke(1), return_exceptions=True
    )
    assert all(isinstance(r, ValueError) for r in results)


def test_coalesce_clear_cancels_sync_waiter() -> None:
    started = threading.Event()
    release = threading.Event()

    def slow(x: int) -> int:
        started.set()
        release.wait(2)
        return x

    runnable = RunnableLambda(slow).with_coalesce()
    leader_result: list[object] = []
    joiner_result: list[object] = []

    def leader() -> None:
        try:
            leader_result.append(runnable.invoke(1))
        except BaseException as e:  # noqa: BLE001
            leader_result.append(e)

    def joiner() -> None:
        try:
            joiner_result.append(runnable.invoke(1))
        except BaseException as e:  # noqa: BLE001
            joiner_result.append(e)

    leader_thread = threading.Thread(target=leader)
    joiner_thread = threading.Thread(target=joiner)
    leader_thread.start()
    assert started.wait(1)
    joiner_thread.start()
    time.sleep(0.2)
    runnable.coalesce_clear()
    joiner_thread.join(1)
    assert len(joiner_result) == 1
    assert isinstance(joiner_result[0], asyncio.CancelledError)

    release.set()
    leader_thread.join(2)
    assert leader_result == [1]
    assert runnable.coalesce_info() == CoalesceStats(active=0, coalesced=0, total=0)


def test_shared_backend_coalesces_across_wrappers() -> None:
    calls: list[int] = []

    def f(x: int) -> int:
        time.sleep(0.1)
        calls.append(x)
        return x

    backend = InMemoryCoalesceBackend()
    runnable_1 = RunnableLambda(f).with_coalesce(backend=backend)
    runnable_2 = RunnableLambda(f).with_coalesce(backend=backend)
    results: list[int] = []

    threads = [
        threading.Thread(target=lambda: results.append(runnable_1.invoke(1))),
        threading.Thread(target=lambda: results.append(runnable_2.invoke(1))),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert results == [1, 1]


def test_separate_wrappers_coalesce_independently() -> None:
    calls: list[int] = []

    def f(x: int) -> int:
        time.sleep(0.1)
        calls.append(x)
        return x

    runnable_1 = RunnableLambda(f).with_coalesce()
    runnable_2 = RunnableLambda(f).with_coalesce()
    results: list[int] = []

    threads = [
        threading.Thread(target=lambda: results.append(runnable_1.invoke(1))),
        threading.Thread(target=lambda: results.append(runnable_2.invoke(1))),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 2


def test_graph_delegation() -> None:
    runnable = RunnableLambda(lambda x: x + 1).with_coalesce()
    assert runnable.get_graph() is not None


def test_transform_passes_through() -> None:
    calls: list[int] = []

    def f(x: int) -> int:
        calls.append(x)
        return x

    runnable = RunnableLambda(f).with_coalesce()
    assert list(runnable.transform(iter([5]))) == [5]
    assert len(calls) == 1


def test_chain_composition_coalesces() -> None:
    calls: list[int] = []

    def f(x: int) -> int:
        time.sleep(0.1)
        calls.append(x)
        return x + 1

    chain = (RunnablePassthrough() | RunnableLambda(f)).with_coalesce()

    async def main() -> list[int]:
        return await asyncio.gather(chain.ainvoke(5), chain.ainvoke(5))

    assert asyncio.run(main()) == [6, 6]
    assert len(calls) == 1


def test_backend_direct_api() -> None:
    backend = InMemoryCoalesceBackend()
    assert backend.register("key") is True
    assert backend.is_active("key") is True
    assert backend.register("key") is False
    assert backend.stats == CoalesceStats(active=1, coalesced=1, total=2)
    backend.complete("key", result="result")
    assert backend.is_active("key") is False
    assert backend.join("key") == "result"
    assert backend.register("key") is True
    backend.complete("key", error=ValueError("bad"))
    with pytest.raises(ValueError):
        backend.join("key")


async def test_backend_async_api() -> None:
    backend = InMemoryCoalesceBackend()
    assert await backend.aregister("key") is True
    assert await backend.ais_active("key") is True
    assert await backend.aregister("key") is False

    async def joiner() -> str:
        return await backend.ajoin("key")

    task = asyncio.create_task(joiner())
    await asyncio.sleep(0.05)
    await backend.acomplete("key", result="result")
    assert await task == "result"
    assert await backend.ais_active("key") is False
