cd /app && python - <<'EOF'
path = 'src/dateutil/rrule.py'
with open(path) as f:
    src = f.read()
old = """        seen_tzids = set()
        for dt in itertools.chain(self._rdate, self._exdate):
            if dt.tzinfo is not None:
                tzid = _tzid(dt)
                if tzid != 'UTC' and tzid not in seen_tzids:
                    seen_tzids.add(tzid)
                    lines.append(_timezone_to_ical(dt.tzinfo, dt))

        for rule in itertools.chain(self._rrule, self._exrule):
            if rule.dtstart is not None and rule.dtstart.tzinfo is not None:
                tzid = _tzid(rule.dtstart)
                if tzid != 'UTC' and tzid not in seen_tzids:
                    seen_tzids.add(tzid)
                    lines.append(_timezone_to_ical(rule.dtstart.tzinfo,
                                                   rule.dtstart))"""
new = """        seen_tzids = set()
        for rule in itertools.chain(self._rrule, self._exrule):
            if rule.dtstart is not None and rule.dtstart.tzinfo is not None:
                tzid = _tzid(rule.dtstart)
                if tzid != 'UTC' and tzid not in seen_tzids:
                    seen_tzids.add(tzid)
                    lines.append(_timezone_to_ical(rule.dtstart.tzinfo,
                                                   rule.dtstart))

        for dt in itertools.chain(self._rdate, self._exdate):
            if dt.tzinfo is not None:
                tzid = _tzid(dt)
                if tzid != 'UTC' and tzid not in seen_tzids:
                    seen_tzids.add(tzid)
                    lines.append(_timezone_to_ical(dt.tzinfo, dt))"""
assert old in src
src = src.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(src)
print("to_ical order fixed")
EOF
cd /app && python -m pytest /tmp/upstream_like_test.py -q 2>&1 | tail -8