cd /app && python - <<'EOF'
from dateutil import parser
dt = parser.parse('19970902T090000Z')
print(dt, repr(dt.tzinfo), type(dt.tzinfo))
from dateutil import tz
print('is UTC:', dt.tzinfo == tz.UTC, 'offset:', dt.tzinfo.utcoffset(dt))
print('tzlocal:', repr(tz.tzlocal()), tz.tzlocal().utcoffset(dt))
EOF