cd /app && python - <<'EOF'
from datetime import datetime
from dateutil.rrule import *

# leading blank line
s = "\nBEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:19970902T090000\nRRULE:FREQ=YEARLY;COUNT=2\nEND:VEVENT\nEND:VCALENDAR\n"
try:
    rr = rrulestr(s)
    print('leading blank OK:', list(rr))
except Exception as e:
    print('leading blank FAIL:', type(e).__name__, e)

# with unfold=True
s2 = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:19970902T090000\nRRULE:FREQ=YEARLY;COUNT=2\nEND:VEVENT\nEND:VCALENDAR\n"
rr2 = rrulestr(s2, unfold=True)
print('unfold=True OK:', list(rr2))

# compatible
rr3 = rrulestr(s2, compatible=True)
print('compatible OK:', type(rr3).__name__, list(rr3))
EOF