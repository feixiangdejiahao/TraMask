cd /app && python - <<'EOF'
path = 'src/dateutil/rrule.py'
with open(path) as f:
    src = f.read()

# Remove the unused _datetime_to_ical_str function
import re
pattern = r"def _datetime_to_ical_str\(dt\):.*?\n\ndef _repr_datetime\(dt\):"
repl = "def _repr_datetime(dt):"
src = re.sub(pattern, repl, src, count=1, flags=re.S)

# Clean up multiple blank lines before helper definitions
src = re.sub(r"\n{3,}def (_tzid|_repr_datetime|_dtstart_ical_str|_date_ical_str|_offset_to_ical|_timezone_to_ical)\(dt\):", r"\n\ndef \1(dt):", src)
src = re.sub(r"\n{3,}def _tzid\(dt\):", "\n\ndef _tzid(dt):", src)

# Fix any remaining 3+ blank lines in helper area
src = re.sub(r"\n{4,}", "\n\n\n", src)

with open(path, 'w') as f:
    f.write(src)
print("cleaned")
EOF
cd /app && sed -n '75,100p' src/dateutil/rrule.py && python -c "import ast; ast.parse(open('src/dateutil/rrule.py').read()); print('syntax ok')"