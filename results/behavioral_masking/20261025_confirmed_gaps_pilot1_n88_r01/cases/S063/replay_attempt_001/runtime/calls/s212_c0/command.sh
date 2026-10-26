cd /app && python - <<'EOF'
try:
    import numpy as np
    print("numpy", np.int64(5), isinstance(np.int64(5), int))
except Exception as e:
    print("no numpy", e)
EOF