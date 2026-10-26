cd /app && python - <<'EOF'
import re
path = 'src/dateutil/rrule.py'
with open(path) as f:
    src = f.read()

# Add helper functions after the FREQNAMES / weekday definitions, before _invalidates_cache
helper = r'''

def _tzid(dt):
    """
    Return the TZID string for a timezone-aware datetime, or None for a naive
    datetime. UTC datetimes return 'UTC'. For other timezones, a name that can
    be resolved by :func:`dateutil.tz.gettz` is preferred when available.
    """
    tzinfo = dt.tzinfo
    if tzinfo is None:
        return None

    offset = tzinfo.utcoffset(dt)
    tzname = getattr(tzinfo, 'tzname', lambda x: None)(dt)

    if offset is not None and offset == datetime.timedelta(0) and tzname in ('UTC', 'GMT'):
        return 'UTC'

    # Prefer a resolvable zoneinfo name where available.
    filename = getattr(tzinfo, '_filename', None)
    if filename:
        for root in ('/usr/share/zoneinfo/', '/usr/lib/zoneinfo/',
                     '/usr/share/lib/zoneinfo/'):
            if filename.startswith(root):
                return filename[len(root):]

    # tzstr objects expose their specification.
    s = getattr(tzinfo, '_s', None)
    if s:
        return s

    return tzname


def _datetime_to_ical_str(dt):
    """
    Format a datetime as an iCalendar DATE-TIME value, using a Z suffix for
    UTC values.
    """
    tzid = _tzid(dt)
    base = dt.strftime('%Y%m%dT%H%M%S')
    if tzid is None:
        return base
    if tzid == 'UTC':
        return base + 'Z'
    return base


def _dtstart_ical_str(dt):
    """
    Format a DTSTART property line, including a TZID parameter for non-UTC
    timezone-aware datetimes and a Z suffix for UTC datetimes.
    """
    tzid = _tzid(dt)
    base = dt.strftime('%Y%m%dT%H%M%S')
    if tzid is None:
        return 'DTSTART:' + base
    if tzid == 'UTC':
        return 'DTSTART:' + base + 'Z'
    return 'DTSTART;TZID={0}:{1}'.format(tzid, base)


def _date_ical_str(dt, name):
    """
    Format an RDATE/EXDATE property line.
    """
    tzid = _tzid(dt)
    base = dt.strftime('%Y%m%dT%H%M%S')
    if tzid is None:
        return '{0}:{1}'.format(name, base)
    if tzid == 'UTC':
        return '{0}:{1}Z'.format(name, base)
    return '{0};TZID={1}:{2}'.format(name, tzid, base)


def _offset_to_ical(offset):
    """
    Convert a :class:`datetime.timedelta` UTC offset to an iCalendar
    TZOFFSETFROM/TZOFFSETTO value (e.g. ``-0500``).
    """
    total = int(offset.total_seconds())
    sign = '+' if total >= 0 else '-'
    total = abs(total)
    return '{0}{1:02d}{2:02d}'.format(sign, total // 3600, (total % 3600) // 60)


def _timezone_to_ical(tzinfo, dt):
    """
    Return an iCalendar VTIMEZONE block for a non-UTC timezone, using the
    UTC offset at *dt* for both TZOFFSETFROM and TZOFFSETTO.
    """
    tzid = _tzid(dt)
    offset = tzinfo.utcoffset(dt)
    offset_str = _offset_to_ical(offset)

    return '\r\n'.join([
        'BEGIN:VTIMEZONE',
        'TZID:{0}'.format(tzid),
        'BEGIN:STANDARD',
        'DTSTART:{0}'.format(dt.strftime('%Y%m%dT%H%M%S')),
        'TZOFFSETFROM:{0}'.format(offset_str),
        'TZOFFSETTO:{0}'.format(offset_str),
        'TZNAME:{0}'.format(tzid),
        'END:STANDARD',
        'END:VTIMEZONE',
    ])
'''

anchor = "def _invalidates_cache(f):"
src = src.replace(anchor, helper + "\n\n" + anchor, 1)

with open(path, 'w') as f:
    f.write(src)
print("helper inserted")
EOF
sed -n '95,220p' src/dateutil/rrule.py