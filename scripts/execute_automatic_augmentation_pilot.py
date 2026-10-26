"""Decode and execute append-only test augmentations without model calls.

The adapter checks syntax and source bindings, not oracle correctness. Native
failure remains an observation until a separate complete-test contract audit.
Python/Go use the seed's existing scope. TypeScript may add relative imports
whose runtime export is proved from original repository source.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import posixpath
import re
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from anchor_retrieval.syntax import Source, child, literal, units
from generic_composition.emitter import emit
from relation_search import contract_gap_proposals as core, direct_generation_provenance, oracle
from relation_search import import_provenance_repair
from scripts import run_contract_gap_generation_search as native
from scripts.run_contract_repair_search import execute as _native_execute, frozen, verify, write
from scripts.resume_test_prefix_probe import try_emit

VERSION = 'automatic-augmentation-native-adapter.v1'
INPUTS = ('corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md')


def read(path):
    return json.loads(Path(path).read_text())


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _identity(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=True))


class OriginalSources:
    """Read original snapshot sources; follow only repository-relative modules."""
    def __init__(self, corpus, repository=None):
        self.corpus = corpus
        self.repository = Path(repository).resolve() if repository else None
        self.cache = {}

    def get(self, path):
        if path in self.cache:
            return self.cache[path]
        if path.startswith('/') or posixpath.normpath(path) != path or path.startswith('../'):
            raise ValueError('import_path_escapes_repository')
        row = self.corpus['sources'].get(path)
        code = row['code'] if row and row.get('origin') == 'repository' else None
        disk = None
        if self.repository:
            disk = (self.repository/path).resolve()
            if not disk.is_relative_to(self.repository):
                raise ValueError('import_symlink_escapes_repository')
            if disk.is_file():
                actual = disk.read_text()
                if code is not None and code != actual:
                    raise ValueError('repository_source_differs_from_frozen_corpus')
                code = actual
        if code is None:
            return None
        source = Source(path, code, 'typescript', 'repository')
        receipt = dict(path=path, sha256=sha(code), origin='repository')
        if disk and disk.is_file():
            receipt['file'] = frozen(disk)
        self.cache[path] = source, receipt
        return source, receipt

    def module(self, owner, module):
        if not module.startswith('.'):
            raise ValueError('new_external_import_not_supported')
        _, path = import_provenance_repair._resolve(owner, module)
        choices = [path]
        if path.endswith('.js'):
            choices.append(path[:-3]+'.ts')
        if not Path(path).suffix:
            choices += [path+'.ts', path+'.tsx', path+'/index.ts', path+'/index.tsx']
        available = [p for p in choices if self.get(p) is not None]
        if len(available) != 1:
            raise ValueError('import_module_missing_or_ambiguous')
        return available[0]

    def export(self, path, name, seen=()):
        """Resolve all export statements, including long barrel files."""
        key = (path, name)
        if key in seen:
            return []
        found = self.get(path)
        if found is None:
            return []
        source, receipt = found
        if source.root.has_error:
            raise ValueError('import_export_source_parse_error')
        result = []
        for node in source.root.named_children:
            if node.type != 'export_statement':
                continue
            text = source.text(node)
            if re.match(r'export\s+type\b', text):
                continue
            declaration = child(node, 'declaration')
            if declaration is not None:
                declarations = ([declaration] if declaration.type not in {'lexical_declaration', 'variable_declaration'}
                                else declaration.named_children)
                for decl in declarations:
                    target = child(decl, 'name')
                    if (target is not None and source.text(target) == name and
                            decl.type in {'function_declaration', 'class_declaration', 'enum_declaration', 'variable_declarator'}):
                        result.append(dict(endpoint=[path, name], sources=[receipt]))
            string = next((c for c in node.named_children if c.type == 'string'), None)
            clause = next((c for c in node.named_children if c.type == 'export_clause'), None)
            if string is None:
                # Local export lists are intentionally unresolved unless the
                # implementation itself is an exported declaration above.
                continue
            module = literal(source.text(string))
            requested = []
            if clause is None and re.match(r'export\s+\*\s+from\b', text):
                requested = [name]
            elif clause is not None:
                for spec in clause.named_children:
                    if re.match(r'type\b', source.text(spec)):
                        continue
                    original, alias = child(spec, 'name'), child(spec, 'alias')
                    if original is not None and source.text(alias or original) == name:
                        requested.append(source.text(original))
            if requested:
                target_path = self.module(path, module)
                for symbol in requested:
                    for proof in self.export(target_path, symbol, (*seen, key)):
                        result.append(dict(endpoint=proof['endpoint'], sources=[receipt, *proof['sources']]))
        return result


def verify_imports(corpus, seed_id, requested, repository=None):
    if not isinstance(requested, list):
        raise ValueError('invalid_imports_schema')
    if requested and corpus['language'] != 'typescript':
        raise ValueError('additional_imports_not_supported_for_language')
    source, _, _ = core._source_test(corpus, seed_id)
    archive = OriginalSources(corpus, repository)
    bindings, proofs, used = [], [], set()
    for row in requested:
        if (not isinstance(row, dict) or set(row) != {'name', 'module', 'imported_name'}
                or any(not isinstance(v, str) or not v for v in row.values())
                or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', row['name'])
                or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', row['imported_name'])):
            raise ValueError('invalid_import_binding_schema')
        if row['name'] in used:
            raise ValueError('duplicate_import_binding')
        used.add(row['name'])
        if row['name'] in source.imports:
            if source.imports[row['name']] != (row['module'], row['imported_name']):
                raise ValueError('import_conflicts_with_existing_import')
            # Exact existing imports need no extra declaration.
            continue
        target = archive.module(source.path, row['module'])
        resolved = archive.export(target, row['imported_name'])
        endpoints = {tuple(p['endpoint']) for p in resolved}
        if len(endpoints) != 1:
            raise ValueError('runtime_export_missing_or_ambiguous')
        proof = sorted(resolved, key=lambda p: (len(p['sources']), json.dumps(p, sort_keys=True)))[0]
        binding = dict(row, source_path=source.path)
        bindings.append(binding)
        proofs.append(dict(binding=binding, **proof))
    return bindings, proofs


def automatic_imports(corpus, seed_id, repository=None):
    """Optional catalog from original donor imports, never an API allowlist."""
    host, _, _ = core._source_test(corpus, seed_id)
    if corpus['language'] != 'typescript':
        return []
    requests = {}
    for path, record in sorted(corpus['sources'].items()):
        if record.get('origin') != 'repository' or not path.endswith(('.ts', '.tsx')):
            continue
        donor = Source(path, record['code'], 'typescript', 'repository')
        for name, (module, member) in donor.imports.items():
            if not module.startswith('.') or not member or name in host.imports:
                continue
            try:
                rebased = import_provenance_repair._rebase(path, module, host.path)
                row = dict(name=name, module=rebased, imported_name=member)
                requests[_identity(row)] = row
            except ValueError:
                continue
    result = []
    for row in requests.values():
        try:
            bindings, proofs = verify_imports(corpus, seed_id, [row], repository)
            if bindings:
                result.append(dict(row, source_proof=proofs[0]))
        except ValueError:
            continue
    return sorted(result, key=lambda row: (row['name'], row['module']))


def _shape(source, node):
    return ((node.type, tuple(_shape(source, c) for c in node.named_children))
            if node.named_children else (node.type, source.text(node)))


def normalize_test(code, original, language):
    """Only remove trailing whitespace or restore an optional TS semicolon."""
    changes = []
    stripped = code.rstrip()
    if code != stripped:
        if language == 'python':
            try:
                same = ast.dump(ast.parse(code)) == ast.dump(ast.parse(stripped))
            except SyntaxError:
                same = False
        else:
            a, b = Source('test', code, language), Source('test', stripped, language)
            same = not a.root.has_error and not b.root.has_error and _shape(a, a.root) == _shape(b, b.root)
        if same:
            code = stripped
            changes.append('trailing_whitespace_only')
    if language == 'typescript' and original.endswith(';') and code.endswith(')'):
        a, b = Source('test.ts', code, language), Source('test.ts', code+';', language)
        if not a.root.has_error and not b.root.has_error and _shape(a, a.root) == _shape(b, b.root):
            code += ';'
            changes.append('optional_registration_semicolon_only')
    return code, changes


def _repository(case):
    if case.get('repository'):
        return case['repository']
    if case.get('source'):
        return read(Path(case['source'])/'case.json')['repository']
    return None


def _complete_seed(corpus, seed):
    seed = deepcopy(seed)
    source, test, _ = core._source_test(corpus, seed['base_test_id'])
    expected = dict(span=test['span'], body_span=test['body_span'], source_sha256=hashlib.sha256(source.data).hexdigest())
    for key, value in expected.items():
        if key in seed and seed[key] != value:
            raise ValueError('seed_binding_changed:' + key)
        seed[key] = value
    return {key: seed[key] for key in ('seed_alias', 'base_test_id', 'span', 'body_span', 'source_sha256')}


def _check_registration_scope(corpus, seed, rewritten):
    source, test, _ = core._source_test(corpus, seed['base_test_id'])
    span = test['span']
    start, end = span['start_byte'], span['end_byte']
    updated = Source(source.path, (source.data[:start] + rewritten.encode() + source.data[end:]).decode(), source.language)
    new_end = start + len(rewritten.encode())
    old_count = sum(u.test and start <= u.node.start_byte and u.node.end_byte <= end for u in units(source)[0])
    new_count = sum(u.test and start <= u.node.start_byte and u.node.end_byte <= new_end for u in units(updated)[0])
    if new_count > old_count:
        raise ValueError('additional_test_registration_in_body')


def decode(corpus, case, response, finish):
    """Strict proposal decoding. All valid rows survive independent of outcome."""
    result = dict(version=VERSION, status='decoded', candidates=[], rejected=[], normalizations=[])
    if finish != 'stop':
        return dict(result, status='unknown', reason='incomplete_provider_response')
    try:
        data = json.loads(response, object_pairs_hook=core._unique_object)
        if (not isinstance(data, dict) or set(data) != {'tests'} or not isinstance(data['tests'], list)
                or len(data['tests']) > case.get('max_candidates', 2)):
            raise ValueError('invalid_response_schema')
    except (TypeError, ValueError) as exc:
        return dict(result, status='unknown', reason=str(exc))
    seeds = {s['seed_alias']: s for s in case['seeds']}
    goals = {g['goal_id']: g['seed_alias'] for g in case.get('goals', [])}
    seen, seen_goals = set(), set()
    for rank, row in enumerate(data['tests'], 1):
        try:
            if (not isinstance(row, dict) or set(row) != {'goal_id', 'seed_alias', 'rewritten_test', 'imports'}
                    or any(not isinstance(row[k], str) for k in ('goal_id', 'seed_alias', 'rewritten_test'))
                    or row['seed_alias'] not in seeds):
                raise ValueError('invalid_test_schema')
            if goals.get(row['goal_id']) != row['seed_alias']:
                raise ValueError('goal_seed_binding_mismatch')
            if row['goal_id'] in seen_goals:
                raise ValueError('duplicate_goal_test')
            seed = _complete_seed(corpus, seeds[row['seed_alias']])
            original = oracle.text(corpus, seed['span'])
            rewritten, changes = normalize_test(row['rewritten_test'], original, corpus['language'])
            candidate = core._rewrite(corpus, seed, rewritten)
            _check_registration_scope(corpus, seed, rewritten)
            candidate['order'] = [rank]
            candidate = direct_generation_provenance.attach(corpus, candidate)
            imports, proofs = verify_imports(corpus, seed['base_test_id'], row['imports'], _repository(case))
            identity = dict(parent=candidate['id'], imports=imports)
            candidate['id'] = 'augmentation_' + _identity(identity)[:24]
            candidate['imports'] = imports
            candidate['augmentation_provenance'] = dict(version=VERSION,
                core_candidate_id=identity['parent'], goal_id=row['goal_id'], seed_alias=row['seed_alias'],
                seed=deepcopy(seed), requested_imports=deepcopy(row['imports']), import_proofs=proofs,
                raw_test_sha256=sha(row['rewritten_test']), normalized_test_sha256=sha(rewritten),
                normalization=changes, repository=str(Path(_repository(case)).resolve()) if _repository(case) else None)
            # The append-only emitter validates lexical import collisions and
            # retains every original byte while adding uniquely named clones.
            emitted = emit(corpus, [candidate])
            if emitted['unsupported']:
                raise ValueError('emission_scope_refusal:' + json.dumps(emitted['unsupported'], sort_keys=True))
            if len(emitted['obligations']) != 1:
                raise ValueError('expected_one_generated_registration')
            if candidate['id'] in seen:
                raise ValueError('duplicate_test')
            seen.add(candidate['id'])
            seen_goals.add(row['goal_id'])
            result['candidates'].append(candidate)
            if changes:
                result['normalizations'].append(dict(rank=rank, changes=changes))
        except (TypeError, ValueError, KeyError, OSError) as exc:
            result['rejected'].append(dict(rank=rank, reason=str(exc)))
    return result


def verify_candidate(corpus, candidate, repository=None):
    p = candidate['augmentation_provenance']
    rewritten = oracle.preview(corpus, candidate)
    rebuilt = core._rewrite(corpus, p['seed'], rewritten)
    _check_registration_scope(corpus, p['seed'], rewritten)
    rebuilt['order'] = candidate['order']
    rebuilt = direct_generation_provenance.attach(corpus, rebuilt)
    if p['version'] != VERSION or p['core_candidate_id'] != rebuilt['id'] or sha(rewritten) != p['normalized_test_sha256']:
        raise ValueError('candidate_source_provenance_mismatch')
    bindings, proofs = verify_imports(corpus, candidate['base_test_id'], p['requested_imports'], repository or p['repository'])
    rebuilt['id'] = 'augmentation_' + _identity(dict(parent=rebuilt['id'], imports=bindings))[:24]
    rebuilt['imports'] = bindings
    rebuilt['augmentation_provenance'] = p
    def proof_identity(rows):
        return [dict(binding=row['binding'], endpoint=row['endpoint'],
                     sources=[{k: s[k] for k in ('path', 'sha256', 'origin')} for s in row['sources']]) for row in rows]
    if rebuilt != candidate or proof_identity(proofs) != proof_identity(p['import_proofs']):
        raise ValueError('candidate_differs_from_source_reconstruction')


def _log_receipts(directory):
    return [frozen(p) for p in sorted(directory.rglob('*')) if p.is_file() and not p.is_symlink()
            and p.suffix in {'.json', '.txt', '.log'}]


def _status(outcome):
    if outcome.get('transport', {}).get('status') != 'matched':
        return 'transport_refused'
    execution = outcome.get('native') or {}
    if execution.get('controls', {}).get('status') != 'all_source_controls_passed':
        return 'original_control_failed_or_unavailable'
    if not execution.get('tests') or execution.get('parser_errors'):
        return 'execution_unknown'
    if native._controlled(outcome):
        return 'controlled_failure'
    if all(t['status'] == 'pass' for t in execution['tests']):
        return 'passed'
    return 'execution_unknown'


def execute(candidate, source, outdir, timeout=180):
    """Run original complete-test controls and one appended candidate twice on failure."""
    source, outdir = Path(source), Path(outdir)
    corpus, case = read(source/'corpus.json'), read(source/'case.json')
    verify_candidate(corpus, candidate, case['repository'])
    inputs = {name: frozen(source/name) for name in INPUTS}
    inputs['candidate_patch'] = frozen(case['candidate_patch'])
    request = dict(version=VERSION, candidate=candidate, source=str(source.resolve()), inputs=inputs,
                   timeout=timeout, algorithm=frozen(__file__),
                   original_control_scope='Complete selected source test clone; not the whole repository suite.',
                   side_effect_scope='Existing test scope and visible bound calls; arbitrary API effects are not proven.')
    write(outdir/'execution_input.json', request)
    write(outdir/'execution_input_seal.json', frozen(outdir/'execution_input.json'))
    outcomes = []
    for phase in ('initial', 'confirmation'):
        for receipt in inputs.values():
            verify(receipt)
        verify_candidate(corpus, candidate, case['repository'])
        directory = outdir/phase
        if (directory/'outcome.json').exists():
            verify(read(directory/'outcome_seal.json'))
            outcome = read(directory/'outcome.json')
            for receipt in outcome.get('logs', []):
                verify(receipt)
        else:
            artifact, refusal = try_emit(candidate, source, directory/'native', dict(timeout=timeout))
            checker = native.csi_repair_transport.verify if corpus['language'] == 'python' else native.verify_emission
            transport = checker(corpus, candidate, artifact) if artifact else dict(status='not_emitted', reason=refusal)
            imported = []
            if artifact and candidate['imports'] and transport['status'] == 'matched':
                for path in sorted((artifact/'generated/files').rglob('*.ts')):
                    rel = str(path.relative_to(artifact/'generated/files'))
                    check = import_provenance_repair.verify_bindings(corpus, candidate, rel, path.read_text())
                    if check['status'] == 'matched':
                        imported.append(dict(path=rel, check=check))
                if not imported:
                    transport = dict(status='mismatch', reason='import_transport_not_verified')
            write(directory/'transport.json', dict(program=transport, imports=imported))
            execution = (_native_execute(candidate, source, corpus, directory/'native', dict(timeout=timeout))
                         if transport['status'] == 'matched' else None)
            outcome = dict(transport=transport, native=execution, emission_refusal=refusal,
                           logs=_log_receipts(directory/'native'))
            write(directory/'outcome.json', outcome)
            write(directory/'outcome_seal.json', frozen(directory/'outcome.json'))
        outcomes.append(dict(phase=phase, status=_status(outcome), receipt=frozen(directory/'outcome.json'),
                             controlled_failure=native._controlled(outcome), native=outcome.get('native')))
        # Repeat any observed test failure, including a failed source control.
        execution = outcome.get('native') or {}
        failed = any(t.get('status') in {'fail', 'error'} for t in execution.get('tests', []))
        failed |= execution.get('controls', {}).get('status') not in {None, 'all_source_controls_passed'}
        if not failed:
            break
    summary = dict(version=VERSION, candidate_id=candidate['id'], goal_id=candidate['augmentation_provenance']['goal_id'],
                   execution_input=frozen(outdir/'execution_input.json'), outcomes=outcomes,
                   repeated_controlled_failure=len(outcomes) == 2 and all(x['controlled_failure'] for x in outcomes),
                   independent_validity='pending_complete_test_contract_audit',
                   substantive_validation_increment='pending_independent_audit',
                   production_edits=False, original_tests_retained=True, provider_calls=0)
    write(outdir/'native_result.json', summary)
    return summary


def execute_all(candidates, source, outdir, timeout=180):
    results = []
    for i, candidate in enumerate(candidates, 1):
        directory = Path(outdir)/f'candidate_{i:02d}'
        try:
            results.append(execute(candidate, source, directory, timeout))
        except (ValueError, OSError, RuntimeError) as exc:
            # One refused/failed materialization must not suppress later rows.
            result = dict(version=VERSION, candidate_id=candidate['id'], status='adapter_error',
                          error=str(exc), traceback=traceback.format_exc(),
                          repeated_controlled_failure=False,
                          independent_validity='pending_complete_test_contract_audit')
            write(directory/'adapter_error.json', result)
            results.append(result)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--decoded', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    results = execute_all(read(args.decoded)['candidates'], args.source, args.output, args.timeout)
    print(json.dumps(dict(candidates=len(results), repeated_controlled_failures=sum(r['repeated_controlled_failure'] for r in results))))
