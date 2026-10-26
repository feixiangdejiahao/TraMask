cd /app && python - <<'EOF'
from datetime import datetime, timezone, timedelta
from dateutil.rrule import *
from dateutil import tz

for t in [timezone(timedelta(hours=5, minutes=30)), timezone(timedelta(hours=-3))]:
    r = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0,tzinfo=t))
    s = str(r)
    print(s)
    try:
        rr = rrulestr(s)
        print('  roundtrip list:', list(r) == list(rr), 'tz:', repr(rr.dtstart.tzinfo))
    except Exception as e:
        print('  FAIL:', type(e).__name__, e)
EOF