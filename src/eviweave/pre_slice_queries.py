"""Issue/Patch queries, role matching and authored-source protection for D."""
from bisect import bisect_right
from collections import Counter
import re

from .anchors import IDENTIFIER


def public_rules(issue, changes, final_sources, sources, *, family):
    snippets = re.findall(r'`+([^`]+)`+', issue)
    examples = '\n'.join(snippets)
    explicit_calls = {name.split('.')[-1] for name in re.findall(r'([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(', examples)}
    single = {s.strip() for s in snippets if IDENTIFIER.fullmatch(s.strip())}
    issue_fields = set(re.findall(r'\.([A-Za-z_$][\w$]*)', examples))
    calls, fields, owners, modified = set(explicit_calls | single), set(issue_fields | single), set(), set()
    for path, raw, parsed in final_sources:
        starts = [0]
        for line in raw.splitlines(keepends=True):
            starts.append(starts[-1] + len(line))
        for line in changes[path]:
            enclosing = [d for d in parsed['declarations'] if d['first_line'] <= line <= d['last_line']]
            if enclosing:
                declaration = min(enclosing, key=lambda d: d['end'] - d['start'])
                modified.add(declaration['name'])
                if declaration['owner']:
                    owners.add(declaration['owner'])
        for unit in parsed['units']:
            for kind in ('calls', 'members', 'keys', 'jsx'):
                names = {name for name, spans in unit[kind].items()
                         if any(bisect_right(starts, start) in changes[path] for start, _ in spans)}
                if kind in {'calls', 'jsx'}:
                    calls.update(names)
                else:
                    fields.update(names)
    calls.update(modified | owners)
    fields.update(modified)
    if family:
        for source in sources:
            calls.update(d['name'] for d in source['parsed']['declarations'] if d['owner'] in owners)
    tokens = set(single)
    tokens.update(re.findall(r'--[a-z][a-z-]+|\#\s*nosec(?:-[a-z-]+)?|\b[a-z]+(?:-[a-z]+)+\b', issue))
    tokens.update(re.findall(r'\|>|:=|\.\.\.', examples))
    for match in re.finditer(r'''["']([^"'\n]+)["']''', examples):
        if len(match[1]) > 1:
            tokens.add(match[1])
    for method, builtin in [('__repr__', 'repr'), ('__str__', 'str'), ('__len__', 'len'), ('__hash__', 'hash')]:
        if method in modified:
            calls.add(builtin)
    return {'calls': calls, 'fields': fields, 'tokens': tokens,
            'protected': explicit_calls | single | modified}


def role_points(sources, rules, *, precise):
    """Keep a seed's call/field role instead of matching it as any identifier."""
    result = {}
    call_patterns = {name: re.compile(rb'\b' + re.escape(name.encode()) + rb'\s*\(') for name in rules['calls']}
    field_patterns = {name: re.compile(rb'(?:\.\s*' + re.escape(name.encode()) + rb'\b|\b'
                                     + re.escape(name.encode()) + rb'\s*[:=])') for name in rules['fields']}
    for source in sources:
        for unit in source['parsed']['units']:
            matches = set()
            for kind, names in [('calls', rules['calls']), ('members', rules['fields']),
                                ('keys', rules['fields']), ('jsx', rules['calls'])]:
                for name in names & unit[kind].keys():
                    matches.update((kind, name, a, b) for a, b in unit[kind][name])
            for kind, names, patterns in [('input_call', rules['calls'], call_patterns),
                                          ('input_field', rules['fields'], field_patterns)]:
                for name in names & unit['input_literals'].keys():
                    for a, b in unit['input_literals'][name]:
                        if not precise or patterns[name].search(source['raw'][a:b]):
                            matches.add((kind, name, a, b))
            for token in rules['tokens']:
                if IDENTIFIER.fullmatch(token):
                    matches.update(('input_token', token, a, b) for a, b in unit['input_literals'].get(token, []))
                else:
                    spans = {tuple(span) for values in unit['input_literals'].values() for span in values}
                    matches.update(('input_token', token, a, b) for a, b in spans
                                   if token.encode() in source['raw'][a:b])
            if matches:
                result[source['id'], unit['start'], unit['end']] = list(matches)
    return result


def frequent_seed_filter(points, protected, threshold):
    """Test frequency pruning of weak seeds; no ranking labels participate."""
    frequency = Counter(name for matches in points.values() for name in {m[1] for m in matches})
    kept = {name for name, count in frequency.items() if count <= threshold or name in protected}
    return {key: [point for point in matches if point[1] in kept]
            for key, matches in points.items()}, kept, dict(frequency)


def authored_anchors(sources):
    """Task-written source stays eligible when pruning repository-wide names.

    These are whole authored scopes, including edit scripts and production
    writes. They are candidates, not a claim that every scope is a useful test.
    """
    return {(source['id'], unit['start'], unit['end']): {(unit['start'], unit['end'])}
            for source in sources if source['kind'] in {'historical_write', 'inline_script'}
            for unit in source['parsed']['units']}
