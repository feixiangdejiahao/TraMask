cd /app && cat > /tmp/repro2.py <<'EOF'
from datetime import datetime
from dateutil import tz
from dateutil.rrule import *
import traceback, datetime as dt_mod

def check(desc, fn):
    try:
        fn()
        print("OK:", desc)
    except Exception as e:
        print("FAIL:", desc, "->", type(e).__name__, e)
        traceback.print_exc()

def t1():
    NYC = tz.gettz('America/New_York')
    r = rrule(YEARLY, count=3, dtstart=datetime(1997, 9, 2, 9, 0, tzinfo=NYC))
    assert 'TZID=America/New_York' in str(r), str(r)
    r2 = rrule(YEARLY, count=3, dtstart=datetime(1997, 9, 2, 9, 0, tzinfo=tz.UTC))
    assert 'DTSTART:19970902T090000Z' in str(r2), str(r2)
    r3 = rrule(YEARLY, count=3, dtstart=datetime(1997, 9, 2, 9, 0))
    assert 'DTSTART:19970902T090000' in str(r3), str(r3)
check("rrule __str__ TZID/Z/naive", t1)

def t2():
    NYC = tz.gettz('America/New_York')
    for dtstart in [datetime(1997,9,2,9,0,tzinfo=NYC), datetime(1997,9,2,9,0,tzinfo=tz.UTC), datetime(1997,9,2,9,0)]:
        r = rrule(YEARLY, count=3, dtstart=dtstart)
        rr = rrulestr(str(r))
        assert list(r) == list(rr), (list(r), list(rr), str(r))
        assert r == rr, (r, rr, str(r))
check("round trip", t2)

def t2b():
    # until with tz
    NYC = tz.gettz('America/New_York')
    r = rrule(DAILY, dtstart=datetime(2020,1,1,9,0,tzinfo=NYC), until=datetime(2020,1,3,9,0,tzinfo=NYC))
    rr = rrulestr(str(r))
    print("until str:", str(r))
    assert list(r) == list(rr), (list(r), list(rr))
check("round trip until tz", t2b)

def t3():
    r = rrule(YEARLY, count=3, dtstart=datetime(1997, 9, 2, 9, 0), until=datetime(2000,1,1))
    assert r.dtstart == datetime(1997, 9, 2, 9, 0)
    assert r.freq == YEARLY
    assert r.interval == 1
    assert r.until == datetime(2000,1,1)
    try:
        r.dtstart = 1
        raise AssertionError("settable")
    except AttributeError:
        pass
check("properties", t3)

def t4():
    r = rrule(YEARLY, count=3, dtstart=datetime(1997, 9, 2, 9, 0))
    assert r.count() == 3
    r2 = rrule(YEARLY, dtstart=datetime(1997, 9, 2, 9, 0), until=datetime(1999,9,2,9,0))
    assert r2.count() == 3
check("count", t4)

def t5():
    r1 = rrule(YEARLY, count=3, dtstart=datetime(1997, 9, 2, 9, 0), byweekday=(MO, TU))
    r2 = rrule(YEARLY, count=3, dtstart=datetime(1997, 9, 2, 9, 0), byweekday=(MO, TU))
    assert r1 == r2
    assert hash(r1) == hash(r2)
    ns = dict(vars(dt_mod))
    ns.update(vars(tz))
    ns.update(globals())
    rr = eval(repr(r1), ns)
    print("repr:", repr(r1))
    assert rr == r1
    # different freq not equal
    r3 = rrule(MONTHLY, count=3, dtstart=datetime(1997,9,2,9,0), byweekday=(MO, TU))
    assert r1 != r3
check("eq/hash/repr", t5)

def t6():
    rs = rruleset()
    rs.rrule(rrule(YEARLY, count=2, dtstart=datetime(1997,9,2)))
    rs.rdate(datetime(1998,1,1))
    rs.exrule(rrule(YEARLY, count=1, dtstart=datetime(1997,9,2)))
    rs.exdate(datetime(1998,1,1))
    assert isinstance(rs.rrules, tuple)
    assert isinstance(rs.rdates, tuple)
    assert isinstance(rs.exrules, tuple)
    assert isinstance(rs.exdates, tuple)
    assert len(rs.rrules) == 1
check("rruleset properties", t6)

def t7():
    rs1 = rruleset(); rs1.rdate(datetime(2020,1,1))
    rs2 = rs1.copy()
    assert rs1 == rs2
    rs3 = rruleset(); rs3.rdate(datetime(2020,2,1))
    ru = rs1.union(rs3)
    assert len(ru.rdates) == 2
    rr1 = rruleset(); rr1.rdate(datetime(2020,1,1))
    rr2 = rruleset(); rr2.rdate(datetime(2020,1,2))
    rs = rr1.subtract(rr2)
    assert len(rs.exdates) == 1
    try:
        rr1.union(3)
        raise AssertionError("no TypeError")
    except TypeError:
        pass
    try:
        rr1.subtract(3)
        raise AssertionError("no TypeError")
    except TypeError:
        pass
check("rruleset copy/union/subtract", t7)

def t8():
    r = rrule(YEARLY, count=3, dtstart=datetime(1997, 9, 2, 9, 0, tzinfo=tz.gettz('America/New_York')))
    ical = r.to_ical()
    assert ical.startswith('BEGIN:VCALENDAR')
    assert 'BEGIN:VEVENT' in ical
    assert 'BEGIN:VTIMEZONE' in ical
    assert 'TZOFFSETFROM:-0400' in ical
    assert 'TZOFFSETTO:-0400' in ical
    r2 = rrule(YEARLY, count=3, dtstart=datetime(1997,9,2,9,0))
    assert 'BEGIN:VTIMEZONE' not in r2.to_ical()
check("to_ical", t8)

def t9():
    rs = rruleset.from_str("DTSTART:19970902T090000\nRRULE:FREQ=YEARLY;COUNT=2")
    assert isinstance(rs, rruleset)
check("from_str", t9)

def t10():
    s = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:STANDARD
DTSTART:19701101T020000
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700308T020000
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
DTSTART;TZID=America/New_York:19970902T090000
RRULE:FREQ=YEARLY;COUNT=3
END:VEVENT
END:VCALENDAR
"""
    r = rrulestr(s)
    print(list(r)[0], list(r)[0].tzinfo)
    assert list(r)[0].tzinfo is not None
    # round trip
    r2 = rrulestr(s)
    assert list(r) == list(r2)
check("rrulestr VCALENDAR", t10)

def t11():
    # RDATE with TZID
    NYC = tz.gettz('America/New_York')
    s = "DTSTART:19970902T090000\nRRULE:FREQ=YEARLY;COUNT=1\nRDATE;TZID=America/New_York:19980101T090000"
    rs = rrulestr(s)
    assert len(rs.rdates) == 1
    assert rs.rdates[0].tzinfo is not None
    # RDATE VALUE=DATE
    s2 = "DTSTART:19970902\nRRULE:FREQ=YEARLY;COUNT=1\nRDATE;VALUE=DATE:19980902"
    rs2 = rrulestr(s2)
    print('rdates', rs2.rdates)
    assert rs2.rdates[0].hour == 0
check("RDATE TZID/VALUE", t11)

def t12():
    # rruleset __str__
    NYC = tz.gettz('America/New_York')
    rs = rruleset()
    rs.rrule(rrule(YEARLY, count=2, dtstart=datetime(1997,9,2,9,0,tzinfo=NYC)))
    rs.rrule(rrule(YEARLY, count=1, byweekday=TU, dtstart=datetime(1997,9,2,9,0,tzinfo=NYC)))
    rs.rdate(datetime(1998,1,1,9,0,tzinfo=NYC))
    rs.exrule(rrule(YEARLY, count=1, dtstart=datetime(1997,9,2,9,0,tzinfo=NYC)))
    rs.exdate(datetime(1999,1,1,9,0,tzinfo=NYC))
    s = str(rs)
    print("rruleset str:\n" + s)
    lines = s.splitlines()
    assert lines[0].startswith('DTSTART;TZID=America/New_York:')
    assert any(l.startswith('RRULE:') for l in lines)
    assert any(l.startswith('RDATE;TZID=America/New_York:') for l in lines)
    assert any(l.startswith('EXRULE:') for l in lines)
    assert any(l.startswith('EXDATE;TZID=America/New_York:') for l in lines)
    # round trip
    rs2 = rrulestr(s)
    assert list(rs) == list(rs2), (list(rs), list(rs2))
check("rruleset __str__", t12)

def t13():
    # rruleset repr
    rs = rruleset()
    rs.rrule(rrule(YEARLY, count=2, dtstart=datetime(1997,9,2)))
    rs.rdate(datetime(1998,1,1))
    print("repr:", repr(rs))
    assert repr(rs).startswith('rruleset()')
    assert '\n.rrule(' in repr(rs)
    assert '\n.rdate(' in repr(rs)
check("rruleset repr", t13)

def t14():
    # rruleset to_ical
    NYC = tz.gettz('America/New_York')
    rs = rruleset()
    rs.rrule(rrule(YEARLY, count=2, dtstart=datetime(1997,9,2,9,0,tzinfo=NYC)))
    rs.rdate(datetime(1998,1,1,9,0,tzinfo=NYC))
    ical = rs.to_ical()
    assert 'BEGIN:VTIMEZONE' in ical
    assert 'TZID:America/New_York' in ical
    # only one VTIMEZONE block per unique tz
    assert ical.count('BEGIN:VTIMEZONE') == 1
check("rruleset to_ical", t14)

def t15():
    # conflicting timezone error message
    try:
        rrulestr("DTSTART;TZID=America/New_York:19970902T090000Z\nRRULE:FREQ=YEARLY;COUNT=3")
        raise AssertionError("no error")
    except ValueError as e:
        assert 'date property specifies multiple timezones' in str(e), str(e)
check("conflicting tz error", t15)

check("all done", lambda: None)
EOF
python /tmp/repro2.py