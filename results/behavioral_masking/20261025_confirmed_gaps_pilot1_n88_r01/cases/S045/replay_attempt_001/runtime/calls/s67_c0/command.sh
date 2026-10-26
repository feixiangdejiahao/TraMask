cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace(
    "from langchain_core.runnables.config import RunnableConfig, ensure_config, get_config_list",
    "from langchain_core.runnables.config import (\n    RunnableConfig,\n    ensure_config,\n    get_config_list,\n    get_executor_for_config,\n)"
)
open(p, 'w').write(s)
print("ok")
PY
cd /app/libs/core && timeout 25 python /tmp/test_coalesce.py 2>&1 | tail -50