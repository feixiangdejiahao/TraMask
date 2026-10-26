cd /app/libs/core && python - <<'PY'
import re
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace("from typing import TYPE_CHECKING, Any, cast, overload", "from typing import TYPE_CHECKING, Any, Literal, cast, overload")
s = s.replace("""        if len(inputs) == 1:
            return [run_one(inputs[0], config[0])]
        with get_config_list(config, len(inputs)) as _:  # noqa: F841
            pass
        # config is already a list of the right length; use it directly.
        with get_executor_for_config(config[0]) as executor:
            return cast(
                "list[Output | Exception]",
                list(executor.map(run_one, inputs, config)),
            )
""", """        if len(inputs) == 1:
            return [run_one(inputs[0], config[0])]
        with get_executor_for_config(config[0]) as executor:
            return cast(
                "list[Output | Exception]",
                list(executor.map(run_one, inputs, config)),
            )
""")
open(p, 'w').write(s)
print("fixed")
PY
nl -ba /app/libs/core/langchain_core/runnables/coalesce.py | sed -n '200,260p'