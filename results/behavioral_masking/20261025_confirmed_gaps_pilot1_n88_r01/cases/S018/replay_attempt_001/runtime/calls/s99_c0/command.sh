cd /app && python - <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import *

rules = [
    rrule(YEARLY, count=3, bymonth=(1,6), bymonthday=(5,-1), bysetpos=(1,-1), dtstart=datetime(1997,9,2,9,0)),
    rrule(WEEKLY, count=3, byweekday=(MO(1), TU(-1)), wkst=SU, dtstart=datetime(1997,9,2,9,0)),
    rrule(MONTHLY, count=3, byeaster=(1,), dtstart=datetime(1997,9,2,9,0)),
    rrule(HOURLY, count=3, byhour=(6,18), byminute=(30,), bysecond=(0,), dtstart=datetime(1997,9,2,9,0,tzinfo=tz.gettz('America/New_York'))),
]
for r in rules:
    rr = eval(repr(r))
    print('OK:', repr(r)[:120])
    assert rr == r
    assert list(rr) == list(r)
print("all complex reprs OK")
EOF