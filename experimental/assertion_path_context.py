"""Render existing Python binding/path facts as source evidence for a reader.

No new analysis, oracle, ranking, subject execution, or model calls. Each cited
function is shown once; paths and possible exits come from assertion_write_origin.
This is an input-context prototype, not a complete program slice.
"""
from __future__ import annotations

import ast
import hashlib

from experimental.assertion_write_origin import Index


def location(span):
    return f"{span['path']}:{span['line']} (bytes {span['start_byte']}:{span['end_byte']})"


class Excerpts:
    def __init__(self, index):
        self.index, self.entries = index, {}
        self.functions = {}
        for path, module in index.paths.items():
            self.functions[path] = [module.span(node) for node in ast.walk(module.tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def reference(self, span):
        # Retain the complete containing function so that local aliasing,
        # branches, protected finally writes and generator syntax remain visible.
        enclosing = [row for row in self.functions[span['path']]
            if row['start_byte'] <= span['start_byte'] and span['end_byte'] <= row['end_byte']]
        scope = min(enclosing, key=lambda row: row['end_byte'] - row['start_byte']) if enclosing else span
        key = (scope['path'], scope['start_byte'], scope['end_byte'])
        if key not in self.entries:
            self.entries[key] = dict(label=f'S{len(self.entries) + 1}', span=scope)
        return f"[{self.entries[key]['label']}] {location(span)}"

    def source(self, span):
        module = self.index.paths[span['path']]
        return module.code_bytes[span['start_byte']:span['end_byte']].decode()

    def render(self):
        chunks = []
        for entry in self.entries.values():
            span = entry['span']
            module = self.index.paths[span['path']]
            lines = module.code.splitlines()[span['line'] - 1:span['end_line']]
            chunks.append(f"{entry['label']}: {span['path']}:{span['line']}-{span['end_line']} "
                f"(source SHA256 {hashlib.sha256(module.code_bytes).hexdigest()})\n"
                + '```python\n' + '\n'.join(f'{n}: {line}' for n, line in enumerate(lines, span['line'])) + '\n```')
        return '\n\n'.join(chunks)


def render_context(sources, analysis, *, index=None):
    """Return deterministic Markdown for one already analyzed source assertion."""
    index = Index(sources) if index is None else index
    excerpts = Excerpts(index)
    lines = ['Static source evidence for one original assertion.',
        'These are source bindings and possible call paths, not proof of execution, '
        'exception feasibility, generator exhaustion, last writer, or expected behavior.',
        'Exit candidates use source-position order, not proven evaluation order or branch feasibility; '
        'for nested calls, the enclosing expression can execute after the inner call.']
    if analysis.get('assertion_span'):
        lines += ['', 'Original assertion: ' + excerpts.reference(analysis['assertion_span']),
                  '    ' + analysis['assertion']]
    if not analysis.get('reads'):
        lines += ['', 'No supported field path: ' + str(analysis.get('reason') or
                   analysis.get('unsupported_reason') or 'no_attribute_read')]
    for position, read in enumerate(analysis.get('reads', []), 1):
        lines += ['', f"Read {position}: `{read['expression']}` at {excerpts.reference(read['read_span'])}"]
        if read['status'] != 'statically_bound_partial_slice':
            lines.append('Unresolved: ' + read['reason'])
            continue
        binding = read['binding']
        lines += [f"Bound constructor: `{excerpts.source(binding['allocation_span'])}` at "
                  + excerpts.reference(binding['allocation_span']),
                  f"Resolved class: `{binding['class_id']}`; observed field `{read['observed_field']}` "
                  f"-> direct storage field `{read['storage_field']}`.",
                  'The test function excerpt shows the assignments/aliases used by this local binding.']
        for alias in read['property_aliases']:
            lines.append(f"Direct property alias `{alias['attribute']}` -> `{alias['storage_attribute']}`: "
                         + excerpts.reference(alias['span']))
        lines.append('Direct writer sites in this resolved class (not all necessarily reachable):')
        for writer in read['writers']:
            lines.append(f"- `{writer['method']}`: `{excerpts.source(writer['span'])}` at "
                         + excerpts.reference(writer['span']))
        lines.append('Syntactic paths from the constructor or earlier operation on this bound object:')
        explained_targets = set()
        if not read['writer_paths']:
            lines.append('- No path recorded; absence is not proof of no influence.')
        for path in read['writer_paths']:
            root = path['root']
            writers = [writer for writer in read['writers'] if writer['method'] == path['writer_method']]
            for writer in writers:
                route = [f"`{excerpts.source(root['span'])}` ({excerpts.reference(root['span'])})",
                         f"`{binding['class_id']}.{root['method']}`"]
                for edge in path['calls']:
                    route.append(f"`{edge['caller']} -> {edge['callee']}` "
                                 f"via `{excerpts.source(edge['span'])}` ({excerpts.reference(edge['span'])})")
                route.append(f"write `{excerpts.source(writer['span'])}` ({excerpts.reference(writer['span'])})")
                lines.append('- ' + ' -> '.join(route))
                if path['requires_generator_runtime_binding']:
                    lines.append('  Generator creation does not establish iteration, resumption or exhaustion.')
                for target in [*path['calls'], writer]:
                    label = f"call `{target['callee']}`" if 'callee' in target else 'field write'
                    span = target['span']
                    key = (span['path'], span['start_byte'], span['end_byte'])
                    if key in explained_targets:
                        lines.append(f"  Context and source-order exit candidates for {label}: "
                                     + excerpts.reference(span) + ' (listed above).')
                        continue
                    explained_targets.add(key)
                    for context in target.get('contexts', []):
                        lines.append(f"  {label} is inside {context['kind']}.{context['branch']} at "
                                     + excerpts.reference(context['span']))
                    sites = target.get('possible_bypass_sites', [])
                    for site in sites:
                        lines.append(f"  Possible source-order exit for {label} ({site['kind']}, may): "
                                     f"`{site['expression']}` at {excerpts.reference(site['span'])}")
                if not any(target.get('possible_bypass_sites') for target in [*path['calls'], writer]):
                    lines.append('  No source-order exit candidate recorded on this path; this is not a no-exception proof.')
        lines.append('Known analysis limits: ' + '; '.join(read['unknown']) + '.')
    if index.parse_errors:
        lines += ['', 'Sources not parsed: ' + ', '.join(index.parse_errors)]
    lines += ['', 'Referenced source functions (each shown once):', '', excerpts.render()]
    return '\n'.join(lines) + '\n'
