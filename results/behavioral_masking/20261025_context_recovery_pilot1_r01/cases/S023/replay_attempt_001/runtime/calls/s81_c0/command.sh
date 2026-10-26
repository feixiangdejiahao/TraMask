cd /app && python - <<'EOF'
path='src/cattrs/converters.py'
s=open(path).read()
s = s.replace(
    "from .fns import Predicate, identity, raise_error\nfrom .partial import PartialResult, partial_structure\nfrom .gen import (\n",
    "from .fns import Predicate, identity, raise_error\nfrom .gen import (\n"
)
# Insert partial import before .typealiases
old = "from .literals import is_literal_containing_enums\nfrom .typealiases import ("
new = "from .literals import is_literal_containing_enums\nfrom .partial import PartialResult, partial_structure\nfrom .typealiases import ("
assert old in s
s = s.replace(old, new)
open(path,'w').write(s)
print("import order fixed")
EOF
sed -n '80,110p' src/cattrs/converters.py