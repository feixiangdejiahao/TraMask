"""Project source defaults along an unchanged, argument-only edited call path.

This is candidate evidence, never an expected-result generator. In particular a
destructuring default creates a local binding; it does not fill the input object.
Only existing frontend actual/formal paths are used. No dispatch/name heuristics
or provider/runtime execution are introduced here.
"""
from __future__ import annotations

import hashlib
import json

from anchor_retrieval.syntax import CALLS, Source, call_parts, child, walk
from generic_composition.corpus import span
from relational_gap.frontend import TRUSTED_RESOLUTIONS, _contexts, _structure, _unwrap
from relation_search.instrument import _program_edits


VERSION = 'call_default_evidence.v1'
APPLICABILITY = 'source_default_not_proved_on_all_paths'
EVIDENCE_ROLE = 'currentcandidatefact_notnormativeoracle'


def _ref(extent):
    return {key: extent[key] for key in ('path', 'start_byte', 'end_byte')}


def _contains(outer, inner):
    return (outer['path'] == inner['path']
            and outer['start_byte'] <= inner['start_byte']
            and inner['end_byte'] <= outer['end_byte'])


def _overlap(a, b):
    return (a['path'] == b['path'] and a['start_byte'] < b['end_byte']
            and b['start_byte'] < a['end_byte'])


class _Projection:
    def __init__(self, corpus, frontend, candidate):
        self.corpus, self.frontend, self.candidate = corpus, frontend, candidate
        self.calls = {row['id']: row for row in frontend.get('calls', []) + frontend.get('production_calls', [])}
        self.functions = {row['id']: row for row in frontend.get('functions', [])}
        self.sources, self.nodes, self.source_hashes = {}, {}, {}
        self.edits = sorted(_program_edits(candidate), key=lambda e: (
            e['span']['path'], e['span']['start_byte'], e['span']['end_byte']))
        self.test = corpus['tests'][candidate['base_test_id']]
        self.owner = self.test['span']['path']
        self.current = None

    def source(self, path):
        if path not in self.sources:
            row = self.corpus['sources'][path]
            extracted = self.frontend.get('sources', {}).get(path)
            if extracted is None or extracted['code'] != row['code']:
                raise ValueError('frontend_source_mismatch')
            source = Source(path, row['code'], row.get('language', self.corpus['language']))
            self.sources[path] = source
            self.nodes[path] = list(walk(source.root))
            self.source_hashes[path] = dict(original_sha256=hashlib.sha256(source.data).hexdigest())
        return self.sources[path]

    def node(self, extent, types=None):
        self.source(extent['path'])
        return next((node for node in self.nodes[extent['path']]
                     if node.start_byte == extent['start_byte'] and node.end_byte == extent['end_byte']
                     and (types is None or node.type in types)), None)

    def snippet(self, extent, *, modified=False, expected=None, max_chars=512):
        source = self.current if modified else self.source(extent['path'])
        start, end = extent['start_byte'], extent['end_byte']
        if source.path != extent['path'] or not 0 <= start <= end <= len(source.data):
            raise ValueError('source_span_out_of_bounds')
        text = source.data[start:end].decode()
        if expected is not None and text != expected:
            raise ValueError('frontend_expression_source_mismatch')
        return dict(ref=dict(version='modified' if modified else 'original', **_ref(extent)),
                    text=text[:max_chars], omitted_chars=max(0, len(text) - max_chars))

    def expression(self, expression):
        return self.snippet(expression['span'], expected=expression.get('text'))

    def prepare(self):
        if self.candidate.get('imports'):
            raise ValueError('added_imports_mapping_not_revalidated')
        source = self.source(self.owner)
        if source.language != 'typescript':
            raise ValueError('field_default_language_unsupported')
        if not self.edits:
            raise ValueError('no_candidate_argument_edits')
        previous = -1
        for edit in self.edits:
            extent = edit['span']
            if not _contains(self.test['span'], extent):
                raise ValueError('edit_outside_selected_test')
            if extent['start_byte'] < previous:
                raise ValueError('overlapping_candidate_edits')
            previous = extent['end_byte']
            self.snippet(extent, expected=edit['before'])
        data = source.data
        for edit in reversed(self.edits):
            extent = edit['span']
            data = data[:extent['start_byte']] + edit['after'].encode() + data[extent['end_byte']:]
        self.current = Source(source.path, data.decode(), source.language)
        if self.current.root.has_error:
            raise ValueError('modified_source_parse_error')
        if self.current.imports != source.imports:
            raise ValueError('changed_imports_mapping_not_revalidated')
        self.source_hashes[self.owner]['modified_sha256'] = hashlib.sha256(data).hexdigest()

    def mapped(self, extent):
        """Map a containing span across edits; callers validate containment first."""
        before = sum(len(e['after'].encode()) - len(e['before'].encode()) for e in self.edits
                     if e['span']['end_byte'] <= extent['start_byte']
                     and not _contains(extent, e['span']))
        inside = sum(len(e['after'].encode()) - len(e['before'].encode()) for e in self.edits
                     if _contains(extent, e['span']))
        return dict(path=extent['path'], start_byte=extent['start_byte'] + before,
                    end_byte=extent['end_byte'] + before + inside)

    def validate_root(self, call):
        if call.get('test_id') != self.candidate['base_test_id']:
            raise ValueError('root_call_test_mismatch')
        old = self.node(call['span'], CALLS)
        if old is None:
            raise ValueError('root_call_source_mismatch')
        old_fn, old_args = call_parts(old)
        old_args = [node for node in old_args if node.type != 'comment']
        old_source = self.source(self.owner)
        if not all(any(_contains(span(old_source, arg), edit['span']) for arg in old_args)
                   for edit in self.edits):
            raise ValueError('edits_not_within_one_call_arguments')
        extent = self.mapped(call['span'])
        new = next((node for node in walk(self.current.root) if node.type in CALLS
                    and node.start_byte == extent['start_byte'] and node.end_byte == extent['end_byte']), None)
        if new is None:
            raise ValueError('modified_call_structure_changed')
        new_fn, new_args = call_parts(new)
        new_args = [node for node in new_args if node.type != 'comment']
        if (old.type != new.type or old_source.text(old_fn) != self.current.text(new_fn)
                or len(old_args) != len(new_args)):
            raise ValueError('callee_receiver_or_argument_slots_changed')
        for old_arg, new_arg in zip(old_args, new_args):
            if self.mapped(span(old_source, old_arg)) != _ref(span(self.current, new_arg)):
                raise ValueError('modified_argument_boundaries_changed')
            if 'spread' in old_arg.type or 'spread' in new_arg.type:
                raise ValueError('spread_argument_mapping_unsupported')
        # This revalidates syntax and the prior resolution metadata. It is not a
        # runtime identity proof or a proof about effects while evaluating args.
        return old_args, new_args

    def guards(self, contexts):
        output = []
        for context in contexts:
            row = dict(kind=context['kind'], branch=context.get('branch'),
                       ref=dict(version='original', **_ref(context['span'])),
                       reachability='not_proved')
            if context.get('condition'):
                row['condition'] = self.expression(context['condition'])
            else:
                # Exact header only, never repeat a callback/control body.
                node = self.node(context['span'])
                if node is not None:
                    body = child(node, 'body', 'consequence')
                    if body is not None and body.start_byte > node.start_byte:
                        row['header'] = self.snippet(dict(path=context['span']['path'],
                            start_byte=node.start_byte, end_byte=body.start_byte))
            output.append(row)
        return output

    def path(self, default, binding):
        path = binding.get('path', [])
        if (binding.get('resolution') != 'resolved_actual_formal_path' or not path
                or path[0]['call_id'] != binding['call_id']):
            raise ValueError('unresolved_actual_formal_path')
        output, previous_target = [], None
        for i, edge in enumerate(path):
            call = self.calls.get(edge['call_id'])
            target = self.functions.get(edge['function_id'])
            if call is None or target is None or edge.get('resolution') not in TRUSTED_RESOLUTIONS:
                raise ValueError('unresolved_path_edge')
            if i and call.get('function_id') != previous_target:
                raise ValueError('disconnected_forwarding_path')
            resolved = [t for t in call.get('targets', []) if t.get('resolved')]
            if len({t['function_id'] for t in resolved}) != 1 or not any(
                    t['function_id'] == target['id'] for t in resolved):
                raise ValueError('ambiguous_or_unresolved_path_target')
            argument = next((a for a in call.get('arguments', []) if a['slot'] == edge['slot']), None)
            parameter = next((p for p in target.get('parameters', []) if p['index'] == edge['parameter_index']), None)
            matched = any(b.get('binding_status') == 'direct_actual_formal'
                          and b.get('function_id') == target['id']
                          and b.get('slot') == edge['slot']
                          and b.get('parameter_index') == edge['parameter_index']
                          and b.get('resolution') == edge['resolution']
                          for b in call.get('argument_bindings', []))
            if (argument is None or parameter is None or not matched
                    or _ref(argument['span']) != _ref(edge['argument_span'])):
                raise ValueError('actual_formal_metadata_mismatch')
            call_node = self.node(call['span'], CALLS)
            if call_node is None or self.node(parameter['span']) is None:
                raise ValueError('forwarding_source_span_mismatch')
            call_source = self.source(call['span']['path'])
            callee, arguments = call_parts(call_node)
            arguments = [node for node in arguments if node.type != 'comment']
            if (call_source.text(callee) != call['callee'] or edge['slot'] >= len(arguments)
                    or _ref(span(call_source, arguments[edge['slot']])) != _ref(argument['span'])):
                raise ValueError('forwarding_call_source_mismatch')
            # Target function bodies can share the test file; edits must still
            # leave all production declarations intact, including their guards.
            if any(_overlap(target['span'], edit['span']) for edit in self.edits):
                raise ValueError('production_function_edited')
            output.append(dict(call_id=call['id'], function_id=target['id'], slot=edge['slot'],
                parameter_index=edge['parameter_index'], resolution=edge['resolution'],
                call=self.snippet(call['span']), actual=self.expression(argument),
                formal=self.snippet(parameter['span']), guards=self.guards(call.get('contexts', []))))
            previous_target = target['id']
        if (previous_target != default['function_id']
                or path[-1]['parameter_index'] != default['parameter_index']
                or path[0]['slot'] != binding['slot']):
            raise ValueError('default_parameter_path_mismatch')
        return output

    def declaration(self, default):
        node = self.node(default['span'])
        function = self.functions[default['function_id']]
        boundary = self.node(function['span'])
        if node is None or boundary is None:
            raise ValueError('default_declaration_source_mismatch')
        source = self.source(default['span']['path'])
        declaration = node
        while declaration.parent is not None and declaration.parent != boundary:
            if declaration.type in {'variable_declarator', 'required_parameter', 'optional_parameter'}:
                break
            declaration = declaration.parent
        if declaration.type not in {'variable_declarator', 'required_parameter', 'optional_parameter'}:
            declaration = node
        elif (declaration.parent.type in {'lexical_declaration', 'variable_declaration'}
              and len(declaration.parent.named_children) == 1):
            declaration = declaration.parent
        return self.snippet(span(source, declaration)), self.guards(_contexts(source, node, boundary))

    def presence(self, node, field_path):
        """Describe object-literal spelling, not runtime values or defaults."""
        for depth, field in enumerate(field_path):
            structure = _structure(self.current, node)
            if structure is None or structure['kind'] != 'record_syntax':
                return dict(status='unknown', reason='non_object_literal_prefix', at=field_path[:depth])
            keys = [item['key'] for item in structure['fields']]
            if not structure['complete_keys'] or len(set(keys)) != len(keys):
                return dict(status='unknown', reason='spread_dynamic_or_duplicate_keys', at=field_path[:depth])
            found = next((item for item in structure['fields'] if item['key'] == field), None)
            if found is None:
                return dict(status='syntax_missing', missing_at=field_path[:depth + 1])
            extent = found['value']['span']
            node = next((n for n in walk(node) if n.start_byte == extent['start_byte']
                         and n.end_byte == extent['end_byte']), None)
            if depth == len(field_path) - 1:
                return dict(status='syntax_present', value=self.snippet(extent, modified=True),
                            value_kind=found['value']['kind'])
        return dict(status='unknown', reason='empty_field_path')


def analyze(corpus, frontend, candidate):
    """Return exact source facts; unknown/empty results never certify validity."""
    result = dict(version=VERSION, candidate_id=candidate.get('id'),
                  base_test_id=candidate.get('base_test_id'), status='unknown', facts=[], unknowns=[],
                  applicability=APPLICABILITY, evidence_role=EVIDENCE_ROLE,
                  default_execution='not_proved', input_object_mutation='not_inferred',
                  control_flow_coverage='frontend_contexts_only_not_complete_path_condition',
                  semantic_validity='unconfirmed', alarm_eligible=False, source_hashes={}, edits=[])
    try:
        projection = _Projection(corpus, frontend, candidate)
        projection.prepare()
        delta = 0
        for edit in projection.edits:
            start = edit['span']['start_byte'] + delta
            extent = dict(path=edit['span']['path'], start_byte=start, end_byte=start + len(edit['after'].encode()))
            result['edits'].append(dict(original=projection.snippet(edit['span'], expected=edit['before']),
                                        modified=projection.snippet(extent, modified=True, expected=edit['after'])))
            delta += len(edit['after'].encode()) - len(edit['before'].encode())
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        result['unknowns'].append(dict(reason=str(error)))
        return result
    candidates = [(default, binding) for default in frontend.get('field_defaults', [])
                  for binding in default.get('caller_bindings', [])
                  if binding.get('test_id') == candidate['base_test_id']]
    seen = set()
    for default, binding in candidates:
        key = (default['id'], binding['call_id'], binding['slot'],
               json.dumps(binding.get('path', []), sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        try:
            root = projection.calls[binding['call_id']]
            # Ignore unrelated calls in the same test without inventing paths.
            if not any(_contains(root['span'], e['span']) for e in projection.edits):
                continue
            old_args, new_args = projection.validate_root(root)
            path = projection.path(default, binding)
            slot = binding['slot']
            old_source = projection.source(projection.owner)
            if slot >= len(new_args):
                raise ValueError('argument_slot_out_of_bounds')
            if _unwrap(new_args[slot]).type != 'object':
                raise ValueError('modified_actual_not_object_literal')
            if not any(_contains(span(old_source, old_args[slot]), e['span']) for e in projection.edits):
                continue
            declaration, guards = projection.declaration(default)
            result['facts'].append(dict(id='D' + str(len(result['facts']) + 1),
                field_default_id=default['id'], field_path=default['field_path'],
                mechanism=default['mechanism'], applicability=APPLICABILITY,
                evidence_role=EVIDENCE_ROLE, declaration=declaration,
                default=projection.expression(default['default']), guards=guards,
                source_expression=(projection.expression(default['source_expression'])
                                   if default.get('source_expression') else None),
                forwarding_path=path,
                original_actual=projection.snippet(span(old_source, old_args[slot])),
                modified_actual=projection.snippet(span(projection.current, new_args[slot]), modified=True),
                field_presence=projection.presence(new_args[slot], default['field_path']),
                mapping_status='argument_only_edit_preserves_source_actual_formal_path',
                runtime_receiver_identity='not_proved', default_execution='not_proved',
                input_object_mutation='not_inferred'))
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            result['unknowns'].append(dict(field_default_id=default.get('id'),
                                           call_id=binding.get('call_id'), reason=str(error)))
    result['source_hashes'] = projection.source_hashes
    if not result['facts'] and not result['unknowns']:
        result['unknowns'].append(dict(reason='no_applicable_resolved_field_default_path'))
    result['status'] = 'partial' if result['facts'] and result['unknowns'] else 'source_facts' if result['facts'] else 'unknown'
    return result


def render(document):
    """Short exact snippets and byte references, without production bodies."""
    def snippet(value):
        ref = value['ref']
        suffix = f" [excerpt; {value['omitted_chars']} characters omitted]" if value['omitted_chars'] else ''
        return (json.dumps(value['text'], ensure_ascii=False) + suffix
                + f" @{ref['version']}:{ref['path']}:{ref['start_byte']}:{ref['end_byte']}")

    def guards(rows):
        for row in rows:
            value = row.get('condition') or row.get('header')
            lines.append(f"  guard {row['kind']}/{row.get('branch')}: "
                         + (snippet(value) if value else json.dumps(row['ref'], sort_keys=True))
                         + ' [reachability not proved]')

    lines = [f"Call default source evidence ({document['status']})",
             APPLICABILITY + '; ' + EVIDENCE_ROLE,
             'Defaults are local source expressions; input object mutation and execution are not inferred.',
             'Argument/receiver evaluation effects and runtime receiver identity remain unproved.',
             'Frontend lexical contexts are retained; they are not a complete path condition.']
    for fact in document['facts']:
        lines.append(f"{fact['id']} field {json.dumps(fact['field_path'])}; {fact['mechanism']}")
        lines.append('  declaration ' + snippet(fact['declaration']))
        lines.append('  default expression ' + snippet(fact['default']))
        guards(fact['guards'])
        lines.append('  original actual ' + snippet(fact['original_actual']))
        lines.append('  modified actual ' + snippet(fact['modified_actual']))
        lines.append('  field presence ' + json.dumps(fact['field_presence'], ensure_ascii=False, sort_keys=True))
        for edge in fact['forwarding_path']:
            lines.append('  call ' + snippet(edge['call']))
            lines.append(f"  actual slot {edge['slot']} " + snippet(edge['actual'])
                         + f" -> formal {edge['parameter_index']} " + snippet(edge['formal']))
            guards(edge['guards'])
    if document['unknowns']:
        lines.append('Unknown boundaries: ' + json.dumps(document['unknowns'], sort_keys=True))
    return '\n'.join(lines) + '\n'
