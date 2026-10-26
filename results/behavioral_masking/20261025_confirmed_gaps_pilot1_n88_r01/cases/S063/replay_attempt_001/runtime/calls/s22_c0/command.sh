cd /app && cat > /tmp/buffer_patch.py <<'PYEOF'
# Show current tail
PYEOF
nl -ba pwnlib/tubes/buffer.py | tail -20