cd /app && python - <<'EOF'
path = 'src/cattrs/__init__.py'
src = open(path).read()
src = src.replace(
    "from .gen import override\n",
    "from .gen import override\nfrom .partial import PartialResult, partial_structure\n",
)
src = src.replace(
    '    "Override",\n' if '    "Override",\n' in src else '    "override",\n',
    '    "PartialResult",\n    "override",\n',
)
# add partial_structure function
src = src.replace(
    "register_unstructure_hook_func = global_converter.register_unstructure_hook_func\nget_structure_hook: Final = global_converter.get_structure_hook\nget_unstructure_hook: Final = global_converter.get_unstructure_hook\n",
    "register_unstructure_hook_func = global_converter.register_unstructure_hook_func\npartial_structure = global_converter.partial_structure\nget_structure_hook: Final = global_converter.get_structure_hook\nget_unstructure_hook: Final = global_converter.get_unstructure_hook\n",
)
open(path, 'w').write(src)
print("cattrs done")
EOF
cat src/cattrs/__init__.py