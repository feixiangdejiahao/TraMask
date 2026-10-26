cd /app && python - <<'EOF'
import re
p = re.compile(r"#\s*nosec(?P<directive>-(?:begin|end|next-line))?(?P<selector>[^#]*)", re.IGNORECASE)
for c in ["# NOSEC-BEGIN", "# NOSEC-END this text is ignored", "# nosec-NEXT-LINE", "# nosec-begin", "# nosec-next-line"]:
    print(repr(c), [m.groupdict() for m in p.finditer(c)])
EOF