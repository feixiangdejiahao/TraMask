"""Independent source-byte audit of optional compact admission facts.

Reads artifacts only; does not import analyzers, providers, or subject programs.
This verifies source provenance and evidence roles, not semantic validity.
"""
from __future__ import annotations

import hashlib
import json
import ast

from scripts.audit_admission_receipts import read, require, unique


def source_versions(record, cache):
    corpus_path = record['inputs']['corpus']['path']
    candidates_path = record['inputs']['candidates']['path']
    if corpus_path not in cache:
        cache[corpus_path] = read(corpus_path)
    if candidates_path not in cache:
        cache[candidates_path] = unique(read(candidates_path), 'id', 'accepted candidate')
    corpus = cache[corpus_path]
    candidate = cache[candidates_path][record['candidate_id']]
    edits = candidate.get('edits', [])
    if candidate.get('instrumentation', {}).get('status') == 'instrumented':
        edits = list(candidate['program_edits'])
        def identity(edit):
            span = edit['span']
            return span['path'], span['start_byte'], span['end_byte'], edit['before'], edit['after']
        for edit in candidate.get('edits', []):
            if (edit.get('role') == 'semantic_expected' and not edit.get('instrumented_prefix')
                    and identity(edit) not in {identity(old) for old in edits}):
                edits.append(edit)
    original = {path: row['code'].encode() for path, row in corpus['sources'].items()}
    modified = dict(original)
    for edit in sorted(edits, key=lambda value: value['span']['start_byte'], reverse=True):
        span = edit['span']
        path, start, end = span['path'], span['start_byte'], span['end_byte']
        require(original[path][start:end].decode() == edit['before'], 'Additional fact source edit mismatch')
        modified[path] = modified[path][:start] + edit['after'].encode() + modified[path][end:]
    selected = corpus['tests'][candidate['base_test_id']]['span']
    return original, modified, selected['path'], selected


def verify_additions(request, analysis, record, cache):
    additional = analysis.get('additional_source_analyses')
    if additional is None:
        return {'present': False}
    require(set(additional) == {'conditional_types', 'call_defaults', 'recovered_controls'},
            'Unexpected additional analysis kind')
    payload = json.loads(request['prompt'])
    original, modified, owner, selected = source_versions(record, cache)
    counts = dict(source_spans=0, exact_snippets=0, controls=0, links=0,
                  conditional_facts=0, default_facts=0)

    def extent(ref, version='modified'):
        require(not ('version' in ref and 'source_version' in ref and ref['version'] != ref['source_version']),
                'Conflicting source version markers')
        version = ref.get('version', ref.get('source_version', version))
        require(version in ('original', 'modified'), 'Unknown source version')
        data = (original if version == 'original' else modified)[ref['path']]
        start, end = ref['start_byte'], ref['end_byte']
        require(0 <= start <= end <= len(data), 'Additional source span out of bounds')
        counts['source_spans'] += 1
        return data[start:end].decode()

    def inspect(value):
        if isinstance(value, dict):
            if {'ref', 'text', 'omitted_chars'} <= set(value):
                text = extent(value['ref'])
                require(value['text'] == text[:512], 'Default source excerpt mismatch')
                require(value['omitted_chars'] == max(0, len(text) - 512), 'Default omitted character count mismatch')
                counts['exact_snippets'] += 1
            elif isinstance(value.get('ref'), dict) and 'path' in value['ref']:
                extent(value['ref'])
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    types = additional['conditional_types']
    for path, module in types.get('modules', {}).items():
        require(hashlib.sha256(modified[path]).hexdigest() == module['source_sha256'],
                'Conditional fact module hash mismatch')
    if types['facts']:
        require(payload.get('conditional_predicate_facts') ==
                {key: types[key] for key in ('premise', 'limitation', 'facts')},
                'Conditional fact provider projection mismatch')
    else:
        require('conditional_predicate_facts' not in payload, 'Empty conditional facts supplied')
    for fact in types['facts']:
        require(fact['check_id'] in payload['checks'], 'Conditional fact has no check')
        check = analysis['analysis']['obligations'][fact['check_id']]
        ref = check.get('predicate') or check.get('expected') or check['at']
        block = analysis['analysis']['sources'][ref['source']]
        span = fact['predicate_span']
        require((span['path'], span['start_byte'], span['end_byte']) ==
                (block['path'], block['start_byte'] + ref['start'], block['start_byte'] + ref['end']),
                'Conditional fact is not attached to the indexed check predicate')
        require(extent(fact['predicate_span']) == fact['predicate'], 'Conditional predicate source mismatch')
        require(fact['implies_test_invalid'] is False, 'Conditional fact promoted to validity judgment')
        for operand in fact['operands']:
            require(extent(operand['span']) == operand['text'], 'Conditional operand source mismatch')
        counts['conditional_facts'] += 1

    controls = additional['recovered_controls']
    original_controls = 'original_source_sha256' in controls
    for key, sources in [('original_source_sha256', original), ('modified_source_sha256', modified)]:
        if key in controls:
            require(hashlib.sha256(sources[owner]).hexdigest() == controls[key],
                    'Recovered controls source version hash mismatch: ' + key)
    if 'source_sha256' in controls:
        require(hashlib.sha256(modified[owner]).hexdigest() == controls['source_sha256'],
                'Recovered controls module hash mismatch')
    for name, key in [('recovered_source_controls', 'controls'), ('source_documentation_links', 'documentation_links')]:
        require(payload.get(name, []) == controls[key], 'Source context provider projection mismatch')
        require(bool(controls[key]) == (name in payload), 'Empty source context supplied')
    for control in controls['controls']:
        if original_controls:
            require(control.get('source_version') == 'original' and control['span'].get('version') == 'original',
                    'Recovered example must explicitly reference original source')
            span = control['span']
            require(span['path'] != selected['path'] or span['end_byte'] <= selected['start_byte']
                    or span['start_byte'] >= selected['end_byte'], 'Recovered example overlaps selected test')
            code = original[span['path']].decode()
            starts = [0]
            for line in code.splitlines(keepends=True):
                starts.append(starts[-1] + len(line.encode()))
            declared = []
            for function in ast.parse(code).body:
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                first = min([function, *function.decorator_list], key=lambda node: (node.lineno, node.col_offset))
                begin = starts[first.lineno - 1] + first.col_offset - int(first is not function)
                end = starts[function.end_lineno - 1] + function.end_col_offset
                declared.append((function.name, begin, end))
            require((control['name'], span['start_byte'], span['end_byte']) in declared,
                    'Recovered example is not an original module-level function')
        require(extent(control['span']) == control['code'], 'Recovered example source mismatch')
        require(control['oracle_validity'] == 'unconfirmed_source_example', 'Example validity promoted')
        for match in control['matches']:
            if original_controls:
                require(match['changed_call'].get('version') == 'modified'
                        and match['example_call'].get('version') == 'original', 'Control call source versions missing')
                changed, example = match['changed_call'], match['example_call']
                require(changed['path'] == owner and selected['start_byte'] <= changed['start_byte']
                        <= changed['end_byte'] <= selected['start_byte'] + len(payload['modified_test'].encode()),
                        'Changed call lies outside complete modified selected test')
                require(example['path'] == control['span']['path']
                        and control['span']['start_byte'] <= example['start_byte']
                        <= example['end_byte'] <= control['span']['end_byte'],
                        'Example call lies outside original recovered example')
            require(match['equivalence_proved'] is False, 'Example equivalence promoted')
            extent(match['changed_call'])
            extent(match['example_call'])
            if match.get('fixture'):
                if original_controls:
                    require(match['fixture'].get('source_version') == 'original'
                            and match['fixture']['span'].get('version') == 'original',
                            'Fixture must explicitly reference original source')
                require(extent(match['fixture']['span']) == match['fixture']['code'], 'Fixture source mismatch')
        counts['controls'] += 1
    for link in controls['documentation_links']:
        if original_controls:
            require(link['span'].get('version') == 'original', 'Documentation link source version missing')
        require(link['url'] in extent(link['span']), 'Documentation URL not present in source span')
        require(link['fetched'] is False and link['normative_status'] == 'not_established_by_link_alone',
                'Documentation link promoted to fetched/normative evidence')
        counts['links'] += 1

    defaults = additional['call_defaults']
    for path, hashes in defaults['source_hashes'].items():
        for version, digest in hashes.items():
            data = (original if version == 'original_sha256' else modified)[path]
            require(hashlib.sha256(data).hexdigest() == digest, 'Default source module hash mismatch')
    inspect(defaults)
    rendered = payload.get('call_default_source_evidence', '')
    require(bool(defaults['facts']) == bool(rendered), 'Default fact provider projection presence mismatch')
    if rendered:
        for text in ('source_default_not_proved_on_all_paths', 'currentcandidatefact_notnormativeoracle',
                     'input object mutation and execution are not inferred', 'runtime receiver identity remain unproved'):
            require(text in rendered, 'Default evidence limitation missing from provider')
        require('Unknown boundaries:' not in rendered, 'Detailed default unknowns unexpectedly supplied')
    for fact in defaults['facts']:
        for key, expected in [('evidence_role', 'currentcandidatefact_notnormativeoracle'),
                              ('applicability', 'source_default_not_proved_on_all_paths'),
                              ('default_execution', 'not_proved'), ('runtime_receiver_identity', 'not_proved'),
                              ('input_object_mutation', 'not_inferred')]:
            require(fact[key] == expected, 'Default evidence role promoted: ' + key)
        def shown(snippet):
            ref = snippet['ref']
            require(json.dumps(snippet['text'], ensure_ascii=False) in rendered, 'Default exact text absent from provider')
            require(f"@{ref['version']}:{ref['path']}:{ref['start_byte']}:{ref['end_byte']}" in rendered,
                    'Default source reference absent from provider')
        for key in ('declaration', 'default', 'original_actual', 'modified_actual'):
            shown(fact[key])
        guards = list(fact['guards'])
        for edge in fact['forwarding_path']:
            for key in ('call', 'actual', 'formal'):
                shown(edge[key])
            guards += edge['guards']
        for guard in guards:
            if guard.get('condition') or guard.get('header'):
                shown(guard.get('condition') or guard['header'])
        require(json.dumps(fact['field_presence'], ensure_ascii=False, sort_keys=True) in rendered,
                'Default field presence absent from provider')
        counts['default_facts'] += 1
    return dict(present=True, **counts, evidence_roles_not_promoted=True,
                original_example_declarations_checked=original_controls,
                binding_identity_and_ranking_correctness_not_proved=True,
                semantic_validity_not_established_by_provenance_audit=True)
