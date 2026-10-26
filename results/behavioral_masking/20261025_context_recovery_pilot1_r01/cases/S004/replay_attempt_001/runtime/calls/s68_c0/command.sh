python - <<'EOF'
import inspect
from click.core import Parameter
print(inspect.getsource(Parameter.shell_complete))
EOF