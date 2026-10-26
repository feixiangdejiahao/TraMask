cd /app && timeout 30 python /tmp/test_flow.py >/tmp/f.log 2>&1 && echo "flow ok" || (echo "flow FAIL"; tail /tmp/f.log)
timeout 30 python /tmp/test_mux_basic.py >/tmp/b.log 2>&1 && echo "basic ok" || (echo "basic FAIL"; tail /tmp/b.log)
timeout 60 python /tmp/test_concurrent.py >/tmp/c.log 2>&1 && echo "concurrent ok" || (echo "concurrent FAIL"; tail /tmp/c.log)