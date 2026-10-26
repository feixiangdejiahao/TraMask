cd /app && python - <<'EOF'
from datetime import datetime
from dateutil.rrule import *

# no rrules, only rdates
rs = rruleset()
rs.rdate(datetime(2020,1,1,9,0))
print("only rdates str:", repr(str(rs)))
rr = rrulestr(str(rs))
print("parsed:", type(rr).__name__, rr.rdates)
assert list(rs) == list(rr)

# only exdate
rs2 = rruleset()
rs2.exdate(datetime(2020,1,1,9,0))
print("only exdate str:", repr(str(rs2)))
rr2 = rrulestr(str(rs2))
assert list(rs2) == list(rr2)

# multiple rrules with second having until etc.
r1 = rrule(YEARLY, count=2, dtstart=datetime(1997,9,2,9,0))
r2 = rrule(MONTHLY, count=2, dtstart=datetime(1997,9,2,9,0))
rs3 = rruleset()
rs3.rrule(r1); rs3.rrule(r2)
print("two rrules str:\n" + str(rs3))
rr3 = rrulestr(str(rs3))
assert list(rs3) == list(rr3)
print("OK")
EOF