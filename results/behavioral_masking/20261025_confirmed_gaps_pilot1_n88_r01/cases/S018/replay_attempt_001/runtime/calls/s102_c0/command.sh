cd /app && python - <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import *
r = rrule(HOURLY, until=datetime(2018,3,6,8,0,tzinfo=tz.UTC))
s = str(r)
print(s)
rr = rrulestr(s)
print('dtstart tzinfo:', rr.dtstart.tzinfo)
assert rr.dtstart.tzinfo is not None
print("OK")
EOF