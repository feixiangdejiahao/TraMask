cd /app && python - <<'EOF'
path = 'src/cattr/__init__.py'
src = open(path).read()
src = src.replace(
    "from .gen import override\n",
    "from .gen import override\nfrom .partial import PartialResult, partial_structure\n",
)
src = src.replace(
    '    "override",\n',
    '    "PartialResult",\n    "override",\n',
)
src = src.replace(
    "register_unstructure_hook_func = global_converter.register_unstructure_hook_func\n",
    "register_unstructure_hook_func = global_converter.register_unstructure_hook_func\npartial_structure = global_converter.partial_structure\n",
)
open(path, 'w').write(src)
print(open(path).read())
EOF