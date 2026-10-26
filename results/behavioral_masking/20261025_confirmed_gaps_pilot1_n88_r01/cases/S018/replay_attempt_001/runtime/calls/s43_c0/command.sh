cd /app && python - <<'EOF'
path = 'src/dateutil/rrule.py'
with open(path) as f:
    src = f.read()

start = src.index("    def __init__(self, cache=False):", src.index("class rruleset"))
end = src.index("    def _iter(self):", src.index("class rruleset"))

new_block = '''    def __init__(self, cache=False):
        super(rruleset, self).__init__(cache)
        self._rrule = []
        self._rdate = []
        self._exrule = []
        self._exdate = []

    @_invalidates_cache
    def rrule(self, rrule):
        """ Include the given :py:class:`rrule` instance in the recurrence set
            generation. """
        self._rrule.append(rrule)
        return self

    @_invalidates_cache
    def rdate(self, rdate):
        """ Include the given :py:class:`datetime` instance in the recurrence
            set generation. """
        self._rdate.append(rdate)
        return self

    @_invalidates_cache
    def exrule(self, exrule):
        """ Include the given rrule instance in the recurrence set exclusion
            list. Dates which are part of the given recurrence rules will not
            be generated, even if some inclusive rrule or rdate matches them.
        """
        self._exrule.append(exrule)
        return self

    @_invalidates_cache
    def exdate(self, exdate):
        """ Include the given datetime instance in the recurrence set
            exclusion list. Dates included that way will not be generated,
            even if some inclusive rrule or rdate matches them. """
        self._exdate.append(exdate)
        return self

    @property
    def rrules(self):
        """The recurrence rules in this set, in insertion order."""
        return tuple(self._rrule)

    @property
    def rdates(self):
        """The recurrence dates in this set, in insertion order."""
        return tuple(self._rdate)

    @property
    def exrules(self):
        """The exclusion rules in this set, in insertion order."""
        return tuple(self._exrule)

    @property
    def exdates(self):
        """The exclusion dates in this set, in insertion order."""
        return tuple(self._exdate)

    def __str__(self):
        lines = []
        if self._rrule:
            lines.append(str(self._rrule[0]))
            for rule in self._rrule[1:]:
                # Include only the RRULE line, not a second DTSTART line.
                lines.extend(str(rule).splitlines()[1:])

        for rdate in self._rdate:
            lines.append(_date_ical_str(rdate, 'RDATE'))
        for exrule in self._exrule:
            lines.append('EXRULE:' + exrule._rrule_str()[len('RRULE:'):])
        for exdate in self._exdate:
            lines.append(_date_ical_str(exdate, 'EXDATE'))

        return '\\n'.join(lines)

    def __eq__(self, other):
        if not isinstance(other, rruleset):
            return NotImplemented
        return (list(self._rrule) == list(other._rrule) and
                sorted(self._rdate) == sorted(other._rdate) and
                list(self._exrule) == list(other._exrule) and
                sorted(self._exdate) == sorted(other._exdate))

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((tuple(self._rrule), tuple(sorted(self._rdate)),
                     tuple(self._exrule), tuple(sorted(self._exdate))))

    def __repr__(self):
        repr_str = 'rruleset()'
        for rule in self._rrule:
            repr_str += '\\n.rrule({!r})'.format(rule)
        for rdate in self._rdate:
            repr_str += '\\n.rdate({!r})'.format(rdate)
        for exrule in self._exrule:
            repr_str += '\\n.exrule({!r})'.format(exrule)
        for exdate in self._exdate:
            repr_str += '\\n.exdate({!r})'.format(exdate)
        return repr_str

    def copy(self):
        """Return a shallow copy of this rruleset."""
        new = rruleset()
        new._rrule = list(self._rrule)
        new._rdate = list(self._rdate)
        new._exrule = list(self._exrule)
        new._exdate = list(self._exdate)
        return new

    def union(self, other):
        """Return a new rruleset with the components of both sets combined."""
        if not isinstance(other, rruleset):
            raise TypeError('rruleset union() requires an rruleset')
        new = self.copy()
        new._rrule.extend(other._rrule)
        new._rdate.extend(other._rdate)
        new._exrule.extend(other._exrule)
        new._exdate.extend(other._exdate)
        return new

    def subtract(self, other):
        """Return a new rruleset excluding the components of *other*."""
        if not isinstance(other, rruleset):
            raise TypeError('rruleset subtract() requires an rruleset')
        new = self.copy()
        new._exrule.extend(other._rrule)
        new._exdate.extend(other._rdate)
        return new

    def to_ical(self):
        """
        Serialize this recurrence set as an iCalendar VCALENDAR. One VTIMEZONE
        block is emitted for each unique non-UTC timezone in the set.
        """
        lines = ['BEGIN:VCALENDAR',
                 'VERSION:2.0',
                 'PRODID:-//dateutil//dateutil//EN']

        seen_tzids = set()
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
                                                   rule.dtstart))

        lines.append('BEGIN:VEVENT')
        lines.append(str(self))
        lines.append('END:VEVENT')
        lines.append('END:VCALENDAR')
        return '\\r\\n'.join(lines)

    @classmethod
    def from_str(cls, s, **kwargs):
        """Create an rruleset by parsing a recurrence string."""
        return rrulestr(s, forceset=True, **kwargs)

'''

src = src[:start] + new_block + src[end:]

with open(path, 'w') as f:
    f.write(src)
print("rruleset updated")
EOF
python -c "import ast; ast.parse(open('src/dateutil/rrule.py').read()); print('syntax ok')"