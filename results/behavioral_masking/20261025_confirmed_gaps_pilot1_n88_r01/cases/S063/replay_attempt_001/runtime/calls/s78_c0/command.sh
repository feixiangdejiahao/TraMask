cd /app && python - <<'EOF'
from pwnlib.tubes.tube import tube
t = tube()
print(type(t), isinstance(t, tube), issubclass(type(t), tube))
from pwnlib.tubes.mux import TubeMultiplexer
print("tube module:", tube.__module__)
print("TubeMultiplexer isinstance check imported tube:", TubeMultiplexer.__init__.__globals__['tube'] is tube)
EOF