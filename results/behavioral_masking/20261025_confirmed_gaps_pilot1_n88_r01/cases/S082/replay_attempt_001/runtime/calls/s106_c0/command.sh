cd /app && python3 - <<'PY'
p='docs/config_file.md'
s=open(p).read()
s=s.replace("""    bail_on_uncaught_error:  [Boolean] whether process should exit with error status when there are top level uncaught errors (via `window.onerror`) (true)
""", """    bail_on_uncaught_error:  [Boolean] whether process should exit with error status when there are top level uncaught errors (via `window.onerror`) (true)
    bail_on_test_failure:    [Boolean|Number] bail on the Nth test failure (true means 1) (false)
""",1)
s=s.replace("""    browser_disconnect_timeout   [Number]  timeout to error after disconnect in seconds (10s)
""", """    bail_on_test_failure         [Boolean|Number]  bail on the Nth test failure (true means 1) (false)
    browser_disconnect_timeout   [Number]  timeout to error after disconnect in seconds (10s)
""",1)
open(p,'w').write(s)
PY
echo done