cd /app && python - <<'EOF'
path='src/cattrs/partial.py'
s=open(path).read()
s = s.replace(
"from .errors import AttributeValidationNote, ClassValidationError, ForbiddenExtraKeysError",
"from .errors import (\n    AttributeValidationNote,\n    ClassValidationError,\n    ForbiddenExtraKeysError,\n)"
)
s = s.replace(
"        if (not is_typeddict and not a.init) or a.name in kwargs or a.name not in failed_fields:",
"        if (\n            (not is_typeddict and not a.init)\n            or a.name in kwargs\n            or a.name not in failed_fields\n        ):"
)
open(path,'w').write(s)
print("wrapped")
EOF
cd /app && awk 'length($0)>88 {print NR": "length($0)" "$0}' src/cattrs/partial.py