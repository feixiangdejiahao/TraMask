cd /app && python - <<'EOF'
path = 'tests/test_rrule.py'
with open(path) as f:
    src = f.read()
old1 = """    def testToStrTzinfo(self):
        NYC = tz.gettz('America/New_York')
        rule = rrule(YEARLY, count=3,
                     dtstart=datetime(1997, 9, 2, 9, 0, tzinfo=NYC))
        self._rrulestr_reverse_test(rule)
        self.assertIn('TZID=', str(rule))"""
new1 = """    def testToStrTzinfo(self):
        NYC = tz.gettz('America/New_York')
        rule = rrule(YEARLY, count=3,
                     dtstart=datetime(1997, 9, 2, 9, 0, tzinfo=NYC))
        self.assertEqual(list(rrulestr(str(rule))), list(rule))
        self.assertIn('TZID=', str(rule))"""
assert old1 in src
src = src.replace(old1, new1, 1)

old2 = """    def testToStrTzinfoUTC(self):
        rule = rrule(YEARLY, count=3,
                     dtstart=datetime(1997, 9, 2, 9, 0, tzinfo=tz.UTC))
        self._rrulestr_reverse_test(rule)
        self.assertIn('DTSTART:19970902T090000Z', str(rule))"""
new2 = """    def testToStrTzinfoUTC(self):
        rule = rrule(YEARLY, count=3,
                     dtstart=datetime(1997, 9, 2, 9, 0, tzinfo=tz.UTC))
        self.assertEqual(list(rrulestr(str(rule))), list(rule))
        self.assertIn('DTSTART:19970902T090000Z', str(rule))"""
assert old2 in src
src = src.replace(old2, new2, 1)

with open(path, 'w') as f:
    f.write(src)
print("fixed")
EOF
cd /app && python -m pytest tests/test_rrule.py -q 2>&1 | tail -3