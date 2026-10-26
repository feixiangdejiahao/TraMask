cd /app && python - <<'EOF'
from bandit.core import nosec
ENABLED = {"B601", "B602", "B603", "B607", "B608"}
s = nosec._evaluate(nosec._tokenize("B60* - B602"), ENABLED)
print(s, s.tests)
s2 = nosec._resolve_selector("B60* - B602", ENABLED, "nosec")
print(s2, s2.tests)
EOF