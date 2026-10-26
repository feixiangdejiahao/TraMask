cd /app && git config user.email "dev@example.com" && git config user.name "Developer" && git commit -m "Add RFC 5545 timezone interoperability to rrule

- RDATE supports TZID, VALUE=DATE and VALUE=DATE-TIME parameters.
- rrule gains timezone-aware __str__, equality/hash/repr, read-only
  property accessors, count() short-circuit, and iCalendar serialization.
- rruleset gains __str__, equality/hash/repr, copy/union/subtract,
  read-only component tuples, iCalendar serialization, and from_str.
- rrulestr auto-detects VCALENDAR, parses inline VTIMEZONE definitions
  with priority over tzids lookups, and handles RFC 5545 line unfolding.
- Fix RFC 5445 comment and conflicting-timezone error message." && git log --oneline -3