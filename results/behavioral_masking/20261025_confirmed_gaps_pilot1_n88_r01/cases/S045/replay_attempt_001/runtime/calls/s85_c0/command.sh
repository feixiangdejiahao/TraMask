cd /app/libs/core && python - <<'PY'
p = 'langchain_core/runnables/coalesce.py'
s = open(p).read()
s = s.replace('''        if len(inputs) == 1:
            return [run_one(inputs[0], config[0])]
        with get_executor_for_config(config[0]) as executor:
            return cast(
                "list[Output | Exception]",
                list(executor.map(run_one, inputs, config)),
            )''',
'''        if len(inputs) == 1:
            return [run_one(inputs[0], config[0])]
        print("DEBUG _batch inputs", [type(x).__name__ for x in inputs], [repr(x) for x in inputs], "backend execs before", list(self.backend._executions.keys()), flush=True)
        with get_executor_for_config(config[0]) as executor:
            out = list(executor.map(run_one, inputs, config))
        print("DEBUG _batch execs after", list(self.backend._executions.keys()), flush=True)
        return cast("list[Output | Exception]", out)''')
open(p,'w').write(s)
PY
cd /app/libs/core && timeout 15 python /tmp/debug.py 2>&1 | head -30