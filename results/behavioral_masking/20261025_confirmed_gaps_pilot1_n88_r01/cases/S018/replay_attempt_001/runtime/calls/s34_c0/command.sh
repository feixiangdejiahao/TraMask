cd /app && python - <<'EOF'
from dateutil import tz
for name in ['EDT', 'EST', 'America/New_York', 'UTC']:
    t = tz.gettz(name)
    print(name, '->', repr(t), type(t))
import datetime
dt = datetime.datetime(1997,9,2,9,0,tzinfo=tz.gettz('America/New_York'))
print('tzname:', dt.tzinfo.tzname(dt), 'utcoffset:', dt.tzinfo.utcoffset(dt))
EOF