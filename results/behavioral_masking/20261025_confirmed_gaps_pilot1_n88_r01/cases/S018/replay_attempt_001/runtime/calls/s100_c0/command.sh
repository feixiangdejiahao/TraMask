cd /app && python - <<'EOF'
from datetime import datetime
from dateutil.rrule import *
r = rrule(YEARLY, dtstart=datetime(1997,9,2,9,0), until=datetime(2000,1,1))
print(repr(r))
rr = eval(repr(r))
assert rr == r
assert list(rr) == list(r)
print("until repr OK")
EOF