cd /app && python - <<'EOF'
path = 'src/dateutil/rrule.py'
with open(path) as f:
    src = f.read()

start = src.index("    def _parse_date_value(self, date_value, parms, rule_tzids,")
end = src.index("    def __call__(self, s, **kwargs):")

new_block = r'''    def _parse_date_value(self, date_value, parms, rule_tzids,
                          ignoretz, tzids, tzinfos):
        global parser
        if not parser:
            from dateutil import parser

        datevals = []
        value_found = False
        TZID = None

        for parm in parms:
            if parm.startswith("TZID="):
                try:
                    tzkey = rule_tzids[parm.split('TZID=')[-1]]
                except KeyError:
                    continue
                if tzids is None:
                    from . import tz
                    tzlookup = tz.gettz
                elif callable(tzids):
                    tzlookup = tzids
                else:
                    tzlookup = getattr(tzids, 'get', None)
                    if tzlookup is None:
                        msg = ('tzids must be a callable, mapping, or None, '
                               'not %s' % tzids)
                        raise ValueError(msg)

                TZID = tzlookup(tzkey)
                continue

            # RFC 5545 3.8.2.4: The VALUE parameter is optional, but may be found
            # only once.
            if parm not in {"VALUE=DATE-TIME", "VALUE=DATE"}:
                raise ValueError("unsupported parm: " + parm)
            else:
                if value_found:
                    msg = ("Duplicate value parameter found in: " + parm)
                    raise ValueError(msg)
                value_found = True

        for datestr in date_value.split(','):
            date = parser.parse(datestr, ignoretz=ignoretz, tzinfos=tzinfos)
            if TZID is not None:
                if date.tzinfo is None:
                    date = date.replace(tzinfo=TZID)
                else:
                    raise ValueError('date property specifies multiple timezones')
            datevals.append(date)

        return datevals

    def _parse_rfc(self, s,
                   dtstart=None,
                   cache=False,
                   unfold=False,
                   forceset=False,
                   compatible=False,
                   ignoretz=False,
                   tzids=None,
                   tzinfos=None):
        global parser
        if compatible:
            forceset = True
            unfold = True

        original_s = s
        TZID_NAMES = dict(map(
            lambda x: (x.upper(), x),
            re.findall('TZID=(?P<name>[^:]+):', original_s)
        ))
        s = s.upper()
        if not s.strip():
            raise ValueError("empty string")
        if unfold:
            lines = s.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i].rstrip()
                if not line:
                    del lines[i]
                elif i > 0 and line[0] == " ":
                    lines[i-1] += line[1:]
                    del lines[i]
                else:
                    i += 1
        else:
            lines = s.split()

        # Auto-detect a VCALENDAR wrapper and extract recurrence properties
        # from the first VEVENT. Inline VTIMEZONE definitions are used to
        # resolve TZID parameters and take priority over the ``tzids`` lookup.
        if lines and lines[0].startswith("BEGIN:VCALENDAR"):
            if not unfold:
                lines = s.splitlines()
                i = 0
                while i < len(lines):
                    line = lines[i].rstrip()
                    if not line:
                        del lines[i]
                    elif i > 0 and line[0] == " ":
                        lines[i-1] += line[1:]
                        del lines[i]
                    else:
                        i += 1

            inline_tzids = {}
            try:
                from . import tz as _tz
                ical = _tz.tzical(original_s)
                for key in ical.keys():
                    inline_tzids[key] = ical.get(key)
            except Exception:
                inline_tzids = {}

            if tzids is None:
                def base_lookup(name):
                    from . import tz as _tz
                    return _tz.gettz(name)
            elif callable(tzids):
                base_lookup = tzids
            else:
                base_lookup = getattr(tzids, 'get', None)
                if base_lookup is None:
                    msg = ('tzids must be a callable, mapping, or None, '
                           'not %s' % tzids)
                    raise ValueError(msg)

            def lookup(name):
                if name in inline_tzids:
                    return inline_tzids[name]
                return base_lookup(name)

            vevent_lines = []
            in_event = False
            for line in lines:
                if line.startswith("BEGIN:VEVENT"):
                    in_event = True
                    continue
                if in_event and line.startswith("END:VEVENT"):
                    break
                if in_event:
                    prop_name = line.split(';', 1)[0].split(':', 1)[0]
                    if prop_name in ('DTSTART', 'RRULE', 'RDATE',
                                     'EXRULE', 'EXDATE'):
                        vevent_lines.append(line)

            if not vevent_lines:
                raise ValueError("no VEVENT found in VCALENDAR")

            lines = vevent_lines
            tzids = lookup

        if (not forceset and len(lines) == 1 and (s.find(':') == -1 or
                                                  s.startswith('RRULE:'))):
            return self._parse_rfc_rrule(lines[0], cache=cache,
                                         dtstart=dtstart, ignoretz=ignoretz,
                                         tzinfos=tzinfos)
        else:
            rrulevals = []
            rdatevals = []
            exrulevals = []
            exdatevals = []
            for line in lines:
                if not line:
                    continue
                if line.find(':') == -1:
                    name = "RRULE"
                    value = line
                else:
                    name, value = line.split(':', 1)
                parms = name.split(';')
                if not parms:
                    raise ValueError("empty property name")
                name = parms[0]
                parms = parms[1:]
                if name == "RRULE":
                    for parm in parms:
                        raise ValueError("unsupported RRULE parm: "+parm)
                    rrulevals.append(value)
                elif name == "RDATE":
                    rdatevals.extend(
                        self._parse_date_value(value, parms,
                                               TZID_NAMES, ignoretz,
                                               tzids, tzinfos)
                    )
                elif name == "EXRULE":
                    for parm in parms:
                        raise ValueError("unsupported EXRULE parm: "+parm)
                    exrulevals.append(value)
                elif name == "EXDATE":
                    exdatevals.extend(
                        self._parse_date_value(value, parms,
                                               TZID_NAMES, ignoretz,
                                               tzids, tzinfos)
                    )
                elif name == "DTSTART":
                    dtvals = self._parse_date_value(value, parms, TZID_NAMES,
                                                    ignoretz, tzids, tzinfos)
                    if len(dtvals) != 1:
                        raise ValueError("Multiple DTSTART values specified:" +
                                         value)
                    dtstart = dtvals[0]
                else:
                    raise ValueError("unsupported property: "+name)
            if (forceset or len(rrulevals) > 1 or rdatevals
                    or exrulevals or exdatevals):
                if not parser and (rdatevals or exdatevals):
                    from dateutil import parser
                rset = rruleset(cache=cache)
                for value in rrulevals:
                    rset.rrule(self._parse_rfc_rrule(value, dtstart=dtstart,
                                                     ignoretz=ignoretz,
                                                     tzinfos=tzinfos))
                for rdate in rdatevals:
                    rset.rdate(rdate)
                for value in exrulevals:
                    rset.exrule(self._parse_rfc_rrule(value, dtstart=dtstart,
                                                      ignoretz=ignoretz,
                                                      tzinfos=tzinfos))
                for value in exdatevals:
                    rset.exdate(value)
                if compatible and dtstart:
                    rset.rdate(dtstart)
                return rset
            else:
                return self._parse_rfc_rrule(rrulevals[0],
                                             dtstart=dtstart,
                                             cache=cache,
                                             ignoretz=ignoretz,
                                             tzinfos=tzinfos)

'''

src = src[:start] + new_block + src[end:]

with open(path, 'w') as f:
    f.write(src)
print("_rrulestr updated")
EOF
python -c "import ast; ast.parse(open('src/dateutil/rrule.py').read()); print('syntax ok')"