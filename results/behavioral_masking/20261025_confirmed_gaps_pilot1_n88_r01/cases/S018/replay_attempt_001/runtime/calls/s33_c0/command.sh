python - <<'EOF'
import dis, marshal, importlib.util, sys
# Load pyc and inspect code names
path = '/root/.local/share/uv/tools/mini-swe-agent/lib/python3.12/site-packages/dateutil/__pycache__/rrule.cpython-312.pyc'
with open(path,'rb') as f:
    data = f.read()
# skip header 16 bytes for py3.7+
code = marshal.loads(data[16:])
names = [c.co_name for c in code.co_consts if hasattr(c,'co_name')]
print('to_ical' in names, 'from_str' in names)
print([n for n in names if 'ical' in n or 'repr' in n or 'hash' in n or 'eq' in n or 'str' in n][:20])
EOF