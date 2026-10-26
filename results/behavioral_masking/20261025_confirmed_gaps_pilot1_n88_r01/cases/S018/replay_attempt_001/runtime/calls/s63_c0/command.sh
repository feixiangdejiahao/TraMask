cd /app && python - <<'EOF'
path = 'src/dateutil/rrule.py'
with open(path) as f:
    src = f.read()
old = """        rlist = []
        self._rdate.sort()
        self._genitem(rlist, iter(self._rdate))
        for gen in [iter(x) for x in self._rrule]:
            self._genitem(rlist, gen)
        exlist = []
        self._exdate.sort()
        self._genitem(exlist, iter(self._exdate))"""
new = """        rlist = []
        self._genitem(rlist, iter(sorted(self._rdate)))
        for gen in [iter(x) for x in self._rrule]:
            self._genitem(rlist, gen)
        exlist = []
        self._genitem(exlist, iter(sorted(self._exdate)))"""
assert old in src
src = src.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(src)
print("_iter fixed")
EOF
cd /app && python - <<'EOF'
from datetime import datetime
from dateutil.rrule import rruleset
rs = rruleset()
rs.rdate(datetime(2020,2,1))
rs.rdate(datetime(2020,1,1))
rs.exdate(datetime(2021,2,1))
rs.exdate(datetime(2021,1,1))
assert rs.rdates == (datetime(2020,2,1), datetime(2020,1,1))
assert rs.exdates == (datetime(2021,2,1), datetime(2021,1,1))
list(rs)
assert rs.rdates == (datetime(2020,2,1), datetime(2020,1,1))
assert rs.exdates == (datetime(2021,2,1), datetime(2021,1,1))
print("insertion order preserved")
EOF
python -m pytest tests/test_rrule.py -q 2>&1 | tail -3