cd /app && python - <<'EOF'
from dateutil import tz
import datetime
t = tz.gettz('America/New_York')
print(type(t))
print([a for a in dir(t) if not a.startswith('__')])
print('_filename:', getattr(t, '_filename', None))
print('_tzid:', getattr(t, '_tzid', None))
try:
    print('repr:', repr(t))
except Exception as e:
    print(e)
# tzstr
ts = tz.tzstr('EST5EDT')
print('tzstr attrs:', [a for a in dir(ts) if not a.startswith('__')])
EOF