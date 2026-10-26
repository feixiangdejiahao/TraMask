cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/__init__.py'
s = open(p).read()

# Add to TYPE_CHECKING imports after runnables.base import block
old = """    from langchain_core.runnables.base import (
        Runnable,
        RunnableBinding,
        RunnableGenerator,
        RunnableLambda,
        RunnableMap,
        RunnableParallel,
        RunnableSequence,
        RunnableSerializable,
        chain,
    )
    from langchain_core.runnables.branch import RunnableBranch"""
new = """    from langchain_core.runnables.base import (
        Runnable,
        RunnableBinding,
        RunnableGenerator,
        RunnableLambda,
        RunnableMap,
        RunnableParallel,
        RunnableSequence,
        RunnableSerializable,
        chain,
    )
    from langchain_core.runnables.branch import RunnableBranch
    from langchain_core.runnables.coalesce import (
        CoalesceBackend,
        CoalesceStats,
        InMemoryCoalesceBackend,
    )"""
assert old in s
s = s.replace(old, new, 1)

# Add to __all__
old_all = """    "aadd",
    "add",
    "chain","""
new_all = """    "aadd",
    "add",
    "CoalesceBackend",
    "CoalesceStats",
    "InMemoryCoalesceBackend",
    "chain","""
assert old_all in s
s = s.replace(old_all, new_all, 1)

# Add to _dynamic_imports
old_dyn = '''    "RunnableBranch": "branch",'''
new_dyn = '''    "RunnableBranch": "branch",
    "CoalesceBackend": "coalesce",
    "CoalesceStats": "coalesce",
    "InMemoryCoalesceBackend": "coalesce",'''
assert old_dyn in s
s = s.replace(old_dyn, new_dyn, 1)

open(p, 'w').write(s)
print("done")
PY
cat langchain_core/runnables/__init__.py | sed -n '1,60p'