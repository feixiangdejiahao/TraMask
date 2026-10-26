cd /app && python - <<'EOF'
path = 'tests/test_rrule.py'
with open(path) as f:
    src = f.read()

rrset_tests = r'''
    def testRruleSetProperties(self):
        rrset = rruleset()
        rule = rrule(YEARLY, count=2, dtstart=datetime(1997, 9, 2, 9, 0))
        rdate = datetime(1998, 1, 1, 9, 0)
        exrule = rrule(YEARLY, count=1, dtstart=datetime(1997, 9, 2, 9, 0))
        exdate = datetime(1998, 2, 2, 9, 0)
        rrset.rrule(rule)
        rrset.rdate(rdate)
        rrset.exrule(exrule)
        rrset.exdate(exdate)
        self.assertEqual(rrset.rrules, (rule,))
        self.assertEqual(rrset.rdates, (rdate,))
        self.assertEqual(rrset.exrules, (exrule,))
        self.assertEqual(rrset.exdates, (exdate,))
        with self.assertRaises(AttributeError):
            rrset.rdates = ()

    def testRruleSetEquality(self):
        rs1 = rruleset()
        rs1.rdate(datetime(2020, 1, 2))
        rs1.rdate(datetime(2020, 1, 1))
        rs2 = rruleset()
        rs2.rdate(datetime(2020, 1, 1))
        rs2.rdate(datetime(2020, 1, 2))
        self.assertEqual(rs1, rs2)
        self.assertEqual(hash(rs1), hash(rs2))

    def testRruleSetRepr(self):
        rrset = rruleset()
        rrset.rrule(rrule(YEARLY, count=2, dtstart=datetime(1997, 9, 2)))
        rrset.rdate(datetime(1998, 1, 1))
        rrset.exdate(datetime(1999, 1, 1))
        r = repr(rrset)
        self.assertTrue(r.startswith('rruleset()'))
        self.assertIn('\n.rrule(', r)
        self.assertIn('\n.rdate(', r)
        self.assertIn('\n.exdate(', r)

    def testRruleSetCopy(self):
        rrset = rruleset()
        rrset.rdate(datetime(2020, 1, 1))
        rrset2 = rrset.copy()
        self.assertEqual(rrset, rrset2)
        rrset2.rdate(datetime(2020, 1, 2))
        self.assertNotEqual(rrset, rrset2)

    def testRruleSetUnion(self):
        rs1 = rruleset()
        rs1.rdate(datetime(2020, 1, 1))
        rs2 = rruleset()
        rs2.rdate(datetime(2020, 1, 2))
        u = rs1.union(rs2)
        self.assertEqual(u.rdates,
                         (datetime(2020, 1, 1), datetime(2020, 1, 2)))
        with self.assertRaises(TypeError):
            rs1.union(3)

    def testRruleSetSubtract(self):
        rs1 = rruleset()
        rs1.rdate(datetime(2020, 1, 1))
        rs2 = rruleset()
        rs2.rdate(datetime(2020, 1, 2))
        sub = rs1.subtract(rs2)
        self.assertEqual(sub.exdates, (datetime(2020, 1, 2),))
        with self.assertRaises(TypeError):
            rs1.subtract(3)

    def testRruleSetToIcal(self):
        NYC = tz.gettz('America/New_York')
        rrset = rruleset()
        rrset.rrule(rrule(YEARLY, count=2,
                          dtstart=datetime(1997, 1, 2, 9, 0, tzinfo=NYC)))
        rrset.rdate(datetime(1998, 1, 1, 9, 0, tzinfo=NYC))
        ical = rrset.to_ical()
        self.assertTrue(ical.startswith('BEGIN:VCALENDAR'))
        self.assertEqual(ical.count('BEGIN:VTIMEZONE'), 1)
        self.assertEqual(list(rrulestr(ical)), list(rrset))

    def testRruleSetFromStr(self):
        rrset = rruleset.from_str(
            "DTSTART:19970902T090000\nRRULE:FREQ=YEARLY;COUNT=2")
        self.assertIsInstance(rrset, rruleset)

    def testRruleSetStr(self):
        rrset = rruleset()
        rrset.rrule(rrule(YEARLY, count=2, dtstart=datetime(1997, 9, 2, 9, 0)))
        rrset.rdate(datetime(1998, 1, 1, 9, 0))
        self.assertEqual(str(rrset),
                         "DTSTART:19970902T090000\n"
                         "RRULE:FREQ=YEARLY;COUNT=2\n"
                         "RDATE:19980101T090000")
        self.assertEqual(list(rrulestr(str(rrset))), list(rrset))
'''

anchor = "\n\nclass WeekdayTest(unittest.TestCase):"
assert anchor in src
src = src.replace(anchor, rrset_tests + "\n" + anchor, 1)

with open(path, 'w') as f:
    f.write(src)
print("rruleset tests added")
EOF
cd /app && python -m pytest tests/test_rrule.py -q 2>&1 | tail -3