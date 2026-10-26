cd /app && python - <<'EOF'
import pwnlib.exception as e
print(e.__file__)
print([x for x in dir(e) if 'Error' in x])
EOF