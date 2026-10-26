cd /app && cat > changes/456.enhancement <<'EOF'
Added task state snapshots to the monitor, allowing capture, inspection, comparison and deletion of frozen running/terminated task state via Python APIs, the terminal UI (``snapshot`` command group) and the web UI (``/snapshots`` page and ``/api/snapshot*`` endpoints)
EOF
echo "entry added"
ruff check aiomonitor tests 2>&1 | tail -40