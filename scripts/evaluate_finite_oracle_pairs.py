"""Read-only paired oracle audit and full-program human review packets.

No provider, subject execution, historical oracle cache, or target truth is read.
Syntax acceptance and independent complete-oracle judgments remain separate.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path


VERSION = 'finite-oracle-pairs-evaluation-v2'
ARMS = ('template', 'expanded')


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def check(condition, message):
    if not condition:
        raise ValueError(message)


def effective_edits(candidate):
    """Mirror the recorded source/probe boundary, without importing generators."""
    if candidate.get('instrumentation', {}).get('status') != 'instrumented':
        return copy.deepcopy(candidate.get('edits', []))
    edits = copy.deepcopy(candidate['program_edits'])
    def identity(edit):
        span = edit['span']
        return (span['path'], span['start_byte'], span['end_byte'], edit['before'], edit['after'])
    for edit in candidate.get('edits', []):
        if (edit.get('role') == 'semantic_expected' and not edit.get('instrumented_prefix')
                and not any(identity(edit) == identity(previous) for previous in edits)):
            edits.append(copy.deepcopy(edit))
    return edits


def apply_source(corpus, candidate):
    owner = corpus['tests'][candidate['base_test_id']]['span']
    original = corpus['sources'][owner['path']]['code'].encode()
    edits = effective_edits(candidate)
    for edit in edits:
        span = edit['span']
        check(span['path'] == owner['path'] and
              owner['start_byte'] <= span['start_byte'] <= span['end_byte'] <= owner['end_byte'],
              'Edit outside original source test')
        check(original[span['start_byte']:span['end_byte']].decode() == edit['before'],
              'Edit before text differs from original source')
    changed = original
    for edit in sorted(edits, key=lambda row: row['span']['start_byte'], reverse=True):
        span = edit['span']
        changed = changed[:span['start_byte']] + edit['after'].encode() + changed[span['end_byte']:]
    delta = sum(len(edit['after'].encode()) - (edit['span']['end_byte'] - edit['span']['start_byte']) for edit in edits)
    return changed[owner['start_byte']:owner['end_byte'] + delta].decode(), changed.decode()


def restore_rendered(text, shared):
    for marker, body in shared.items():
        text = text.replace(marker, body)
    return text


def expand_sources(payload):
    source = payload['test_source']
    if payload['representation'] == 'expanded':
        rows = [(row['candidate'], row['modified_test']) for row in source]
    else:
        check(len(source['segments']) == len(source['holes']) + 1, 'Incomplete source segments')
        rows = []
        for variant in source['variants']:
            check(len(variant['replacements']) == len(source['holes']), 'Incomplete replacement tuple')
            parts = []
            for segment, hole, replacement in zip(source['segments'], source['holes'], variant['replacements']):
                check(hole['id'] == replacement['hole_id'], 'Wrong hole identity')
                parts.extend((segment, replacement['after']))
            rows.append((variant['candidate'], ''.join(parts) + source['segments'][-1]))
    check(len({alias for alias, _ in rows}) == len(rows), 'Duplicate member source alias')
    return dict(rows)


def original_assertions(corpus, frontend, candidate):
    result, seen = [], set()
    for observation in frontend.get('observations', []):
        if observation.get('test_id') != candidate['base_test_id'] or observation.get('kind') != 'assertion':
            continue
        span = observation.get('assertion_span', observation.get('span'))
        key = (span['path'], span['start_byte'], span['end_byte'])
        if key in seen:
            continue
        seen.add(key)
        code = corpus['sources'][span['path']]['code'].encode()[span['start_byte']:span['end_byte']].decode()
        result.append(dict(span=span, code=code, observed=observation.get('observed', {}).get('text', '')))
    return result


def verify_prepared(root):
    """Recompute pair identity from sealed source artifacts, never trust booleans."""
    root = Path(root)
    ready, protocol = read(root / 'ready.json'), read(root / 'protocol.json')
    check(sha(root / 'protocol.json') == ready['protocol_sha256'], 'Prepared protocol SHA mismatch')
    for name, expected in read(root / 'seal.json')['files_sha256'].items():
        check(sha(root / name) == expected, 'Prepared sealed file changed: ' + name)
    for name, expected in protocol['code_sha256'].items():
        check(sha(root / 'code_snapshot' / name) == expected, 'Prepared code snapshot changed: ' + name)
    check(protocol['arms'] == list(ARMS), 'Unexpected paired arms')
    check([row['case'] for row in ready['records']] == protocol['cases'], 'Prepared case order changed')
    inventory, packets = Path(protocol['inventory']), []
    for record in ready['records']:
        case = record['case']
        for name, expected in protocol['input_sha256'][case].items():
            check(sha(inventory / case / name) == expected, 'Source inventory changed: ' + case + '/' + name)
        if record['status'] != 'offerable':
            packets.append(dict(case=case, prepared_status=record['status'], members=[]))
            continue
        corpus, frontend = read(inventory / case / 'corpus.json'), read(inventory / case / 'frontend.json')
        pool = {row['id']: row for row in read(inventory / case / 'source_pool.json')['candidates']}
        requests, payloads, sources, wires = {}, {}, {}, {}
        for arm in ARMS:
            entry = record['arms'][arm]
            check(sha(entry['request']) == entry['request_sha256'], 'Prepared request SHA changed')
            check(sha(entry['wire_preview']) == entry['wire_preview_sha256'], 'Prepared wire SHA changed')
            request = requests[arm] = read(entry['request'])
            payload = payloads[arm] = json.loads(request['prompt'])
            check(payload['representation'] == arm, 'Mislabeled representation')
            sources[arm], wires[arm] = expand_sources(payload), read(entry['wire_preview'])
            expected_wire = {**protocol['model_settings'], 'messages': [dict(role='system', content=request['system']),
                dict(role='user', content=request['prompt'])]}
            check(wires[arm] == expected_wire, 'Prepared model settings or messages changed')
            check(request['finite_members'] == record['member_ids'], 'Offered candidate identity changed')
            check(request['family_id'] == record['family_id'], 'Family identity changed')
            offered_sha = hashlib.sha256(json.dumps(request['offered'], sort_keys=True).encode()).hexdigest()
            check(offered_sha == request['candidate_source_hash'], 'Offered source fingerprint changed')
        a, b = copy.deepcopy(payloads['template']), copy.deepcopy(payloads['expanded'])
        for payload in (a, b):
            payload.pop('representation'); payload.pop('test_source')
        check(a == b, 'Common paired prompt information differs')
        check(requests['template']['system'] == requests['expanded']['system'], 'Paired SYSTEM differs')
        for key in ('offered', 'analysis_evidence', 'finite_members', 'family_id', 'candidate_source_hash', 'source_prepared'):
            check(requests['template'][key] == requests['expanded'][key], 'Paired local records differ: ' + key)
        check(sources['template'] == sources['expanded'], 'Source expansion differs between arms')
        check(sha(record['issue_source']) == record['issue_sha256'], 'Issue source changed')
        request = requests['template']
        check(list(request['offered']) == [row['candidate'] for row in a['variants']], 'Member aliases differ')
        check(len(request['offered']) == record['members'], 'Prepared member count changed')
        members = []
        for alias, offered in request['offered'].items():
            candidate, evidence = offered['candidate'], request['analysis_evidence'][alias]
            check(candidate == pool[candidate['id']], 'Offered candidate differs from frozen source pool')
            source, changed_file = apply_source(corpus, candidate)
            check(source == sources['template'][alias], 'Template differs from independently applied source edits')
            member = next(row for row in a['variants'] if row['candidate'] == alias)
            check(restore_rendered(member['dependency_evidence']['rendered'], a['shared_code']) == evidence['rendered'],
                  'Shared CODE_BLOCK evidence does not restore exactly')
            declaration_sources = []
            owner_path = corpus['tests'][candidate['base_test_id']]['span']['path']
            for declaration in evidence['declarations']:
                span = declaration['span']
                choices = [corpus['sources'][span['path']]['code']]
                if span['path'] == owner_path:
                    choices.append(changed_file)
                check(any(sha_text(text) == declaration['source_sha256'] and
                    text.encode()[span['start_byte']:span['end_byte']].decode() == declaration['code'] for text in choices),
                    'Declaration span or source SHA does not match frozen source')
                declaration_sources.append(dict(span=span, source_sha256=declaration['source_sha256'],
                    roles=declaration.get('roles', []), corpus=str((inventory / case / 'corpus.json').resolve())))
            members.append(dict(alias=alias, candidate_id=candidate['id'], base_test_id=candidate['base_test_id'],
                input_test=source, input_test_sha256=sha_text(source),
                original_assertions=original_assertions(corpus, frontend, candidate),
                import_bindings=member['import_bindings'], offered_assertions=offered['assertions'],
                source_evidence=declaration_sources, arms={}))
        check([row['candidate_id'] for row in members] == record['member_ids'], 'Candidate/member order differs')
        packets.append(dict(case=case, family_id=record['family_id'], prepared_status='offerable',
            issue_contract=a['issue'], issue_source=record['issue_source'], issue_sha256=record['issue_sha256'],
            corpus=str((inventory / case / 'corpus.json').resolve()),
            frontend=str((inventory / case / 'frontend.json').resolve()), members=members,
            requests=requests, wires=wires, corpus_value=corpus, source_record=record))
    return protocol, ready, packets


def model_rows(content, aliases):
    """Interpret coverage independently; absent/invalid rows never preserve."""
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        payload = None
    rows = payload.get('results') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > len(aliases):
        return {alias: dict(status='invalid_answer', rows=[]) for alias in aliases}
    outcomes = {alias: dict(status='unanswered', rows=[]) for alias in aliases}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('candidate'), str) or row['candidate'] not in outcomes:
            continue
        item = outcomes[row['candidate']]
        item['rows'].append(row)
        if len(item['rows']) > 1:
            item['status'] = 'duplicate_answer'
            continue
        status, updates = row.get('status'), row.get('updates')
        good = (isinstance(status, str) and status in {'keep', 'revise', 'unknown'} and
            isinstance(updates, list) and isinstance(row.get('basis'), str) and
            all(isinstance(update, dict) and isinstance(update.get('assertion'), str)
                and isinstance(update.get('code'), str) for update in updates))
        item['status'] = status if good and ((status == 'revise' and bool(updates)) or
            (status in {'keep', 'unknown'} and not updates)) else 'invalid_answer'
    return outcomes


def diagnostic(code, old, language):
    if language != 'python':
        return code
    try:
        before, after = ast.parse(old), ast.parse(code)
        if (len(before.body) == len(after.body) == 1 and isinstance(before.body[0], ast.Assert)
                and isinstance(after.body[0], ast.Assert) and before.body[0].msg is not None and after.body[0].msg is None):
            after.body[0].msg = before.body[0].msg
            return ast.unparse(after.body[0])
    except (ValueError, TypeError, SyntaxError):
        pass
    return code


def proposal(corpus, offered, interpretation):
    # Missing prose justification is an interface failure, not missing oracle
    # content. Recover only a single explicit, well-formed keep/revise vector;
    # duplicate rows, malformed updates and unknown remain without a proposal.
    if len(interpretation['rows']) != 1:
        return None, []
    row = interpretation['rows'][0]
    status, updates = row.get('status'), row.get('updates')
    if (not isinstance(status, str) or status not in {'keep', 'revise'}
            or not isinstance(updates, list)
            or not all(isinstance(update, dict) and isinstance(update.get('assertion'), str)
                       and isinstance(update.get('code'), str) for update in updates)
            or (status == 'keep' and updates) or (status == 'revise' and not updates)):
        return None, []
    candidate, edits, used = copy.deepcopy(offered['candidate']), [], set()
    for update in updates:
        alias = update['assertion']
        if alias not in offered['assertions'] or alias in used:
            return None, []
        used.add(alias)
        assertion = offered['assertions'][alias]
        code = diagnostic(update['code'], assertion['code'], corpus['language'])
        if code != assertion['code']:
            edits.append(dict(span=assertion['span'], before=assertion['code'], after=code, role='semantic_expected'))
    candidate['edits'].extend(edits)
    return apply_source(corpus, candidate)[0], edits


def completion(root, case, arm, request, preview):
    folder = Path(root) / case / arm / 'completion'
    result = dict(provider_status='not_dispatched', folder=str(folder.resolve()), answer=None,
        response_sha256=None, usage=None, seconds=None, external_model_calls=0, validation=None)
    if not (folder / 'manifest.json').exists():
        return result
    manifest = read(folder / 'manifest.json')
    result.update(provider_status=manifest['status'], manifest_sha256=sha(folder / 'manifest.json'),
        finish_reason=manifest.get('finish_reason'), usage=manifest.get('usage'), seconds=manifest.get('seconds'),
        external_model_calls=manifest.get('external_model_calls', 0))
    check(read(folder / 'request.json') == preview, 'Actual wire differs from paired preview')
    check(sha(folder / 'request.json') == manifest['request_sha256'], 'Actual wire fingerprint differs')
    check(manifest['request_id'] == request['id'], 'Completion belongs to another prepared question')
    if manifest['status'] not in {'prepared', 'dispatching'} and (folder / 'response.body').exists():
        check(sha(folder / 'response.body') == manifest['response_sha256'], 'Raw provider response fingerprint differs')
        result['response_sha256'] = sha(folder / 'response.body')
    if manifest['status'] != 'complete':
        return result
    check(manifest['external_model_calls'] == 1, 'Complete response does not record exactly one provider call')
    response = read(folder / 'response.json')
    check(response == read(folder / 'response.body'), 'Provider JSON differs from raw response')
    answer = response['choices'][0]['message']['content']
    check(isinstance(answer, str) and (folder / 'completion.txt').read_text() == answer, 'Completion text differs from response')
    result.update(answer=answer, response_json=str((folder / 'response.json').resolve()),
        response_json_sha256=sha(folder / 'response.json'))
    if (folder / 'validation.json').exists():
        result.update(validation=read(folder / 'validation.json'), validation_sha256=sha(folder / 'validation.json'))
    return result


def attach_answers(root, packet):
    request_stats = {}
    if packet['prepared_status'] != 'offerable':
        return request_stats
    corpus = packet['corpus_value']
    for arm in ARMS:
        request = packet['requests'][arm]
        completed = completion(root, packet['case'], arm, request, packet['wires'][arm])
        request_stats[arm] = {key:value for key,value in completed.items() if key not in {'answer', 'validation'}}
        interpretations = (model_rows(completed['answer'], request['offered']) if completed['answer'] is not None
            else {alias:dict(status='unanswered', rows=[]) for alias in request['offered']})
        validation = completed['validation']
        checked = {row['alias']:row for row in validation.get('members', [])} if validation else {}
        check(not validation or len(validation.get('members', [])) == len(checked) == len(request['offered'])
              and set(checked) == set(request['offered']),
              'Validation member inventory differs')
        revisions = {}
        for revised in validation.get('revisions', []) if validation else []:
            parent = revised['semantic_revision']['parent']
            check(parent not in revisions, 'More than one accepted revision for a member')
            revisions[parent] = revised
        for member in packet['members']:
            alias, cid = member['alias'], member['candidate_id']
            interpretation = interpretations[alias]
            proposed, edits = proposal(corpus, request['offered'][alias], interpretation)
            status = checked.get(alias, {}).get('status', 'validation_unavailable')
            if alias in checked:
                check(checked[alias]['candidate_id'] == cid, 'Validation candidate identity differs')
                if interpretation['status'] not in {'keep', 'revise'}:
                    check(status == interpretation['status'], 'Unknown/omitted answer claimed valid coverage')
            accepted_test = None
            if status in {'keep', 'revise'}:
                check(status == interpretation['status'] and proposed is not None, 'Acceptance differs from actual model answer')
                if status == 'keep':
                    check(cid not in revisions, 'Keep member has an accepted revision')
                    accepted_test = member['input_test']
                else:
                    check(cid in revisions and bool(edits), 'Revise acceptance has no changed oracle')
                    revised = revisions[cid]
                    original = request['offered'][alias]['candidate']
                    check(revised['edits'] == original['edits'] + edits, 'Accepted revision changes more than offered oracle edits')
                    mutable = {'id', 'edits', 'semantic_revision', 'static_parent_id', 'execution_lane'}
                    check({key:value for key,value in revised.items() if key not in mutable} ==
                          {key:value for key,value in original.items() if key not in mutable},
                          'Accepted revision changes inputs, imports, or source context')
                    check(revised['semantic_revision']['request_id'] == request['id'], 'Revision belongs to another request')
                    accepted_test = apply_source(corpus, revised)[0]
                    check(accepted_test == proposed, 'Accepted complete test differs from actual answer')
            member['arms'][arm] = dict(model_status=interpretation['status'], raw_rows=interpretation['rows'],
                explicit_oracle_status=interpretation['rows'][0].get('status') if proposed is not None else None,
                raw_answer=completed['answer'], response_sha256=completed['response_sha256'],
                response_folder=completed['folder'], recorded_structural_status=status,
                structurally_accepted=status in {'keep', 'revise'}, proposed_test=proposed,
                proposed_test_sha256=sha_text(proposed) if proposed is not None else None,
                accepted_test=accepted_test, accepted_test_sha256=sha_text(accepted_test) if accepted_test is not None else None,
                oracle_edits=edits, semantic_verdict='unreviewed')
    return request_stats


def review_template(ready_sha, packets):
    return dict(prepared_ready_sha256=ready_sha, reviews=[dict(case=packet['case'],
        candidate_id=member['candidate_id'], arm=arm, response_sha256=value['response_sha256'],
        proposed_test_sha256=value['proposed_test_sha256'], verdict='unreviewed', reason='')
        for packet in packets for member in packet['members'] for arm,value in member['arms'].items()])


def apply_reviews(ledger, ready_sha, packets):
    check(ledger['prepared_ready_sha256'] == ready_sha, 'Review ledger belongs to another prepared cohort')
    index = {(packet['case'], member['candidate_id'], arm):value for packet in packets
        for member in packet['members'] for arm,value in member['arms'].items()}
    seen = set()
    for row in ledger['reviews']:
        key = row['case'], row['candidate_id'], row['arm']
        check(key in index and key not in seen, 'Unknown or duplicate semantic review member')
        seen.add(key)
        value = index[key]
        check(row['response_sha256'] == value['response_sha256'] and
              row['proposed_test_sha256'] == value['proposed_test_sha256'], 'Semantic review evidence changed')
        verdict = row['verdict']
        check(verdict in {'correct', 'incorrect', 'uncertain', 'unreviewed'}, 'Unknown semantic review verdict')
        check(isinstance(row.get('reason'), str) and (verdict == 'unreviewed' or bool(row['reason'].strip())),
              'Complete-oracle review needs a reason')
        check(verdict != 'correct' or value['proposed_test'] is not None and value['explicit_oracle_status'] in {'keep', 'revise'},
              'Missing or unknown answer cannot be a correct complete oracle')
        value.update(semantic_verdict=verdict, semantic_reason=row['reason'])


def evaluate(root, reviews=None):
    root = Path(root)
    protocol, ready, packets = verify_prepared(root)
    request_stats = {packet['case']:attach_answers(root, packet) for packet in packets}
    ready_sha = sha(root / 'ready.json')
    ledger_template = review_template(ready_sha, packets)
    if reviews is not None:
        apply_reviews(reviews, ready_sha, packets)
    counts = {}
    for arm in ARMS:
        members = [member['arms'][arm] for packet in packets for member in packet['members']]
        requests = [row[arm] for row in request_stats.values() if arm in row]
        counts[arm] = dict(offered_members=len(members), model_statuses=dict(Counter(v['model_status'] for v in members)),
            structural_statuses=dict(Counter(v['recorded_structural_status'] for v in members)),
            structurally_accepted=sum(v['structurally_accepted'] for v in members),
            accepted_revisions=sum(v['recorded_structural_status'] == 'revise' for v in members),
            semantic_verdicts=dict(Counter(v['semantic_verdict'] for v in members)),
            correct_and_structurally_accepted=sum(v['semantic_verdict'] == 'correct' and v['structurally_accepted'] for v in members),
            entire_family_correct=sum(bool(packet['members']) and all(member['arms'][arm]['semantic_verdict'] == 'correct'
                for member in packet['members']) for packet in packets),
            provider_statuses=dict(Counter(v['provider_status'] for v in requests)),
            observed_provider_calls=sum(v['external_model_calls'] for v in requests),
            prompt_tokens=sum((v['usage'] or {}).get('prompt_tokens', 0) for v in requests),
            completion_tokens=sum((v['usage'] or {}).get('completion_tokens', 0) for v in requests),
            total_tokens=sum((v['usage'] or {}).get('total_tokens',
                (v['usage'] or {}).get('prompt_tokens', 0) + (v['usage'] or {}).get('completion_tokens', 0)) for v in requests),
            missing_usage=sum(v['usage'] is None for v in requests),
            seconds=sum(v['seconds'] or 0 for v in requests))
    for packet in packets:
        for name in ('requests', 'wires', 'corpus_value', 'source_record'):
            packet.pop(name, None)
    summary = dict(version=VERSION, prepared_ready_sha256=ready_sha, protocol_sha256=sha(root / 'protocol.json'),
        prepare_seal_sha256=sha(root / 'seal.json'), evaluator_sha256=sha(__file__),
        offered_pairs=ready['totals']['offerable_pairs'], offered_members_per_arm=ready['totals']['members_per_arm'],
        counts=counts, evaluator_provider_calls=0, evaluator_subject_executions=0, main_campaign_credit=0,
        interpretation='Code factorization amortization only. Acceptance is syntax/interface evidence; semantic verdicts require a separately supplied complete-program review. No gap or issue-resolution score is inferred.')
    return dict(summary=summary, packets=packets, request_stats=request_stats, review_template=ledger_template)


def write_outputs(output, result):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in [('summary.json', result['summary']), ('review_packet.json', result['packets']),
                        ('request_audit.json', result['request_stats']), ('review_ledger_template.json', result['review_template'])]:
        (output / name).write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reviews', type=Path)
    args = parser.parse_args()
    result = evaluate(args.input, read(args.reviews) if args.reviews else None)
    write_outputs(args.output, result)
    print(json.dumps(result['summary'], ensure_ascii=False))
