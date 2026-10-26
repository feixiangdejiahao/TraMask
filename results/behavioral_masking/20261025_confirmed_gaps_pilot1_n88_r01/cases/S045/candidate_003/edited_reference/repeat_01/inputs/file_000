import time
from langchain_core.runnables import RunnableLambda

def test_batch_coalesces_per_item() -> None:
    calls: list[int] = []

    def f(x: int) -> int:
        time.sleep(0)
        calls.append(x)
        return x + 1

    runnable = RunnableLambda(f).with_coalesce().with_config({"max_concurrency": 1})
    out = runnable.batch([1, 2, 1, 1, 2])
    assert out == [2, 3, 2, 2, 3]
    assert sorted(calls) == [1, 2]

