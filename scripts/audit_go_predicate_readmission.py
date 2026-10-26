"""Replay complete Go oracle responses through current syntax admission only.

No provider, runner, generator, evaluation label or oracle cache is imported.
Original artifacts stay unchanged. Output is compatibility evidence, never a
new reasoning result or proof that an admitted expectation is correct.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from anchor_retrieval.syntax import Source, child, walk
from relation_search import oracle
from prototypes.assertion_operand_guard import valid_assertion


CODE_FILES = ['scripts/audit_go_predicate_readmission.py', 'relation_search/oracle.py',
    'prototypes/assertion_operand_guard.py', 'prototypes/singleton_oracle_slots.py',
    'anchor_retrieval/graph.py', 'anchor_retrieval/syntax.py', 'relation_search/impact_selection.py',
    'relation_search/instrument.py', 'relation_search/oracle_evidence.py']
PAIRS = [frozenset(pair) for pair in [('NoError', 'Error'), ('Nil', 'NotNil'),
                                     ('Empty', 'NotEmpty'), ('True', 'False')]]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)+'\n')


def load_guard(path):
    spec = importlib.util.spec_from_file_location('frozen_go_predicate_audit_guard', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.valid_assertion


def validate_with_guard(request, completion, corpus, guard=None):
    # A private function copy avoids mutating the current validator module.
    validator = oracle.validate
    if guard is not None:
        validator = FunctionType(validator.__code__,
            {**validator.__globals__, '_valid_assertion': guard}, validator.__name__, validator.__defaults__)
    try:
        return validator(request, completion, corpus)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        return dict(revisions=[], decisions=[], error=type(error).__name__)


def predicate_only_change(before, after, observed):
    """Independently compare AST leaves, permitting only one selector token.

    This does not call the production predicate extractor or structural guard.
    It verifies receiver and every argument including diagnostics unchanged.
    """
    def parse(code):
        source = Source('audit_test.go', 'package audit\nfunc check(){\n'+code+'\n}', 'go')
        if source.root.has_error:
            return None
        functions = [n for n in source.root.named_children if n.type == 'function_declaration']
        body = child(functions[0], 'body')
        statements = [n for n in body.named_children if n.type != 'comment']
        # Go grammar wraps statement_list inside block on some parser versions.
        if len(statements) == 1 and statements[0].type == 'statement_list':
            statements = [n for n in statements[0].named_children if n.type != 'comment']
        if len(statements) != 1 or statements[0].type != 'expression_statement':
            return None
        call = statements[0].named_children[0]
        if call.type != 'call_expression':
            return None
        callee, arguments = child(call, 'function'), child(call, 'arguments')
        if callee is None or callee.type != 'selector_expression' or arguments is None:
            return None
        receiver, member = child(callee, 'operand'), child(callee, 'field')
        args = [n for n in arguments.named_children if n.type != 'comment']
        if receiver is None or source.text(receiver) not in {'assert', 'require'} or len(args) < 2:
            return None
        def leaves(node):
            return [(n.type, source.text(n)) for n in walk(node) if not n.children and n.type != 'comment']
        actual = source.text(args[1])
        # Replace only the predicate member token in the complete statement.
        tokens = [(n.type, '<predicate>' if n.id == member.id else source.text(n))
                  for n in walk(statements[0]) if not n.children and n.type != 'comment']
        return source.text(member), tokens, leaves(args[1]), actual
    left, right = parse(before), parse(after)
    if left is None or right is None or left[0] == right[0]:
        return False
    actual_source = Source('expression_test.go', 'package audit\nvar observation = '+observed, 'go')
    values = [n for n in walk(actual_source.root) if n.type == 'var_spec']
    if actual_source.root.has_error or len(values) != 1:
        return False
    value = child(values[0], 'value')
    expected_actual = [(n.type, actual_source.text(n)) for n in walk(value)
                       if not n.children and n.type != 'comment']
    return (frozenset((left[0], right[0])) in PAIRS and left[1] == right[1]
            and left[2] == right[2] == expected_actual)


def relaxed_updates(request, completion, legacy_guard):
    try:
        payload = json.loads(completion)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict) or not isinstance(payload.get('revisions', []), list):
        return []
    records = []
    for row in payload.get('revisions', []):
        if not isinstance(row, dict):
            continue
        offered = request['offered'].get(row.get('candidate'))
        if not offered or not isinstance(row.get('updates'), list):
            continue
        for update in row['updates']:
            if not isinstance(update, dict):
                continue
            hole = offered['assertions'].get(update.get('assertion'))
            if hole is None:
                continue
            code = update.get('code')
            old = legacy_guard(code, hole['code'], hole['observed'], 'go')
            new = valid_assertion(code, hole['code'], hole['observed'], 'go')
            if old != new:
                records.append(dict(candidate=offered['candidate']['id'], assertion=update.get('assertion'),
                    old_admitted=old, new_admitted=new, before=hole['code'], after=code,
                    observed=hole['observed'], span=hole['span'],
                    independently_verified_predicate_only=(not old and new and
                        predicate_only_change(hole['code'], code, hole['observed']))))
    return records


def audit_completion(request_path, directory, corpus_path, legacy_guard):
    paths = [request_path, corpus_path, directory/'manifest.json']
    for name in ['validation.json', 'completion.txt', 'response.body', 'response.json', 'request.json']:
        if (directory/name).is_file():
            paths.append(directory/name)
    hashes = {str(p.resolve()): digest(p) for p in paths}
    request, manifest, corpus = read(request_path), read(directory/'manifest.json'), read(corpus_path)
    if corpus['language'] != 'go':
        raise ValueError('audit_completion requires Go source')
    record = dict(request=str(request_path.resolve()), request_id=request['id'],
        completion_directory=str(directory.resolve()), provider_status=manifest['status'],
        files_sha256=hashes, original_validation=read(directory/'validation.json')
            if (directory/'validation.json').exists() else None, replayed=False)
    if manifest['status'] != 'complete':
        record['not_replayed_reason'] = 'provider_response_not_complete'
        return record
    if manifest['request_id'] != request['id']:
        raise ValueError('provider request identity mismatch')
    if hashlib.sha256(request['prompt'].encode()).hexdigest() != request['id']:
        raise ValueError('frozen prompt identity mismatch')
    completion = (directory/'completion.txt').read_text()
    wire = read(directory/'request.json')
    if wire['messages'] != [dict(role='system', content=request['system']), dict(role='user', content=request['prompt'])]:
        raise ValueError('wire prompt mismatch')
    if digest(directory/'request.json') != manifest['request_sha256']:
        raise ValueError('wire request hash mismatch')
    if digest(directory/'response.body') != manifest['response_sha256']:
        raise ValueError('provider response hash mismatch')
    body = read(directory/'response.body')
    if body != read(directory/'response.json') or body['choices'][0]['message']['content'] != completion:
        raise ValueError('completion does not match provider response')
    old = validate_with_guard(request, completion, corpus, legacy_guard)
    new = validate_with_guard(request, completion, corpus)
    relaxed = relaxed_updates(request, completion, legacy_guard)
    old_ids = {r['id'] for r in old['revisions']}
    record.update(replayed=True, legacy_guard_replay=old, current_validation=new,
        legacy_reproduces_recorded=(old == record['original_validation']),
        changed=(old != new), relaxed_updates=relaxed,
        only_predicate_admission_changed=all(r['independently_verified_predicate_only'] for r in relaxed),
        newly_admitted_revisions=[r for r in new['revisions'] if r['id'] not in old_ids],
        removed_revision_ids=sorted(old_ids-{r['id'] for r in new['revisions']}))
    if any(digest(p) != sha for p, sha in hashes.items()):
        raise ValueError('audit input changed during replay')
    return record


def run(campaign, output):
    output.mkdir(parents=True, exist_ok=False)
    current_hashes = {name:digest(ROOT/name) for name in CODE_FILES}
    snapshot = campaign/'algorithm_snapshot/prototypes/assertion_operand_guard.py'
    legacy_guard = load_guard(snapshot)
    inventory, excluded = [], []
    for semantic in sorted(campaign.glob('*/round_*/semantic')):
        corpus = semantic.parent/'prepared/corpus.json'
        if not corpus.exists() or read(corpus)['language'] != 'go':
            continue
        if not (semantic.parent/'feedback.json').exists():
            excluded.append(dict(round=str(semantic.parent.resolve()), reason='round_feedback_not_complete'))
            continue
        stage = read(semantic/'stage.json')
        old_sha = stage['code_sha256']['prototypes/assertion_operand_guard.py']
        if old_sha != digest(snapshot):
            raise ValueError('frozen guard does not match completed round')
        source_case = semantic.parent.parent.name
        cfg = read(campaign/'configuration.json')
        if digest(corpus) != cfg['source_corpus_sha256'][source_case]:
            raise ValueError('source corpus version mismatch')
        for request in sorted((semantic/'requests').glob('*.json')):
            directory = semantic/'completions'/request.stem
            inventory.append(dict(case=source_case, round=semantic.parent.name,
                request=str(request.resolve()), directory=str(directory.resolve()), corpus=str(corpus.resolve()),
                round_completion_sha256=digest(semantic.parent/'feedback.json'),
                original_code_sha256=stage['code_sha256'], source_corpus_sha256=digest(corpus)))
    protocol = dict(created_at=datetime.now(timezone.utc).isoformat(), campaign=str(campaign.resolve()),
        campaign_configuration_sha256=digest(campaign/'configuration.json'), inventory=inventory, excluded_rounds=excluded,
        current_code_sha256=current_hashes, frozen_guard_sha256=digest(snapshot), provider_calls=0,
        subject_executions=0, selection='every request in Go rounds with completed feedback at audit start',
        interpretation='structural interface compatibility replay, not new reasoning or semantic correctness')
    write(output/'protocol.json', protocol)
    for name in CODE_FILES:
        destination = output/'code_snapshot'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT/name).read_bytes())
    rows = []
    for item in inventory:
        record = audit_completion(Path(item['request']), Path(item['directory']), Path(item['corpus']), legacy_guard)
        record.update(case=item['case'], round=item['round'])
        rows.append(record)
        write(output/item['case']/item['round']/(Path(item['request']).stem+'.json'), record)
    active = [r for r in rows if r['replayed']]
    summary = dict(rounds=len({(r['case'],r['round']) for r in rows}), requests=len(rows),
        complete_responses=len(active), status_counts=dict(Counter(r['provider_status'] for r in rows)),
        changed_responses=sum(r['changed'] for r in active),
        old_revisions=sum(len(r['legacy_guard_replay']['revisions']) for r in active),
        new_revisions=sum(len(r['current_validation']['revisions']) for r in active),
        newly_admitted_revisions=sum(len(r['newly_admitted_revisions']) for r in active),
        removed_revisions=sum(len(r['removed_revision_ids']) for r in active),
        legacy_reproduces_recorded=all(r['legacy_reproduces_recorded'] for r in active),
        only_predicate_admission_changed=all(r['only_predicate_admission_changed'] for r in active),
        cases={case:dict(requests=sum(r['case']==case for r in rows),
            new_revisions=sum(len(r['newly_admitted_revisions']) for r in active if r['case']==case))
            for case in sorted({r['case'] for r in rows})})
    write(output/'summary.json', summary)
    if {name:digest(ROOT/name) for name in CODE_FILES} != current_hashes:
        raise ValueError('audit code changed during replay; output is not sealed')
    write(output/'seal.json', dict(files_sha256={str(p.relative_to(output)):digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.campaign, args.output), sort_keys=True))
