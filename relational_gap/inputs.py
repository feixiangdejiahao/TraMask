"""Bounded source selection and recovery of trajectory validation files.

Selection reads only agent-visible artifacts. No repository/API-specific names,
target labels, verifier logs, or expected failure reports enter this module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import posixpath

from anchor_retrieval.syntax import SKIP, Source, diff_lines, is_test_path, trajectory_sources, units, walk
from relational_gap.history import recover_history, namespace_go_validation, go_duplicate_declarations
from relational_gap.source_dependencies import dependency_closure


@dataclass(frozen=True)
class SourceBudget:
    max_test_files: int = 160
    max_production_files: int = 160
    max_history_files: int = 64
    max_file_bytes: int = 500_000
    max_total_bytes: int = 12_000_000


def module_configuration(repository):
    """Use explicit root TS compiler paths, never infer an alias by spelling."""
    config_path = repository/'tsconfig.json'
    if not config_path.is_file():
        return {}, []
    try:
        text = config_path.read_text()
        # Preserve string literals while stripping JSONC comments.
        clean = re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/',
                       lambda match: match[1] or '', text, flags=re.S)
        config = json.loads(clean).get('compilerOptions', {})
        aliases = config.get('paths', {})
        base = config.get('baseUrl', '.')
        if not isinstance(aliases, dict) or not isinstance(base, str) or Path(base).is_absolute():
            return {}, [{'path': 'tsconfig.json', 'reason': 'unsupported_module_configuration'}]
        normalized = posixpath.normpath(base)
        if normalized == '..' or normalized.startswith('../'):
            return {}, [{'path': 'tsconfig.json', 'reason': 'module_base_escapes_repository'}]
        if any(not isinstance(key, str) or not isinstance(value, list)
               or any(not isinstance(item, str) for item in value) for key, value in aliases.items()):
            return {}, [{'path': 'tsconfig.json', 'reason': 'invalid_paths_configuration'}]
        return {'module_aliases': aliases, 'module_base_url': normalized}, []
    except (ValueError, UnicodeError, OSError, AttributeError):
        return {}, [{'path': 'tsconfig.json', 'reason': 'unparsed_module_configuration'}]


def _relative_written(path: str | None) -> str | None:
    if not path:
        return None
    for prefix in ('/app/', '/repo/'):
        if path.startswith(prefix):
            path = path[len(prefix):]
    p = Path(path)
    if p.is_absolute() or '..' in p.parts:
        return None
    return p.as_posix()


def select_sources(case: dict, budget: SourceBudget = SourceBudget()) -> tuple[list[Source], dict]:
    repository = Path(case['repository']).resolve()
    language = case['language']
    patch = Path(case['candidate_patch']).read_text()
    changed = diff_lines(patch)
    extensions = {'python': {'.py'}, 'go': {'.go'}, 'typescript': {'.ts', '.tsx'}}[language]
    files, changed_symbols, omitted = {}, set(), []
    for path in sorted(repository.rglob('*')):
        relative = path.relative_to(repository)
        if (not path.is_file() or path.suffix not in extensions or set(relative.parts) & SKIP
                or not path.resolve().is_relative_to(repository)):
            continue
        if path.stat().st_size > budget.max_file_bytes:
            omitted.append({'path': relative.as_posix(), 'reason': 'file_bytes'})
            continue
        try:
            text = path.read_text()
        except UnicodeError:
            omitted.append({'path': relative.as_posix(), 'reason': 'encoding'})
            continue
        name = relative.as_posix()
        files[name] = text
        if name in changed and not is_test_path(name):
            source = Source(name, text, language)
            for unit in units(source)[0]:
                if any(unit.node.start_point.row + 1 <= line <= unit.node.end_point.row + 1 for line in changed[name]):
                    changed_symbols.add(unit.name)
                    if unit.owner:
                        changed_symbols.add(unit.owner)
    # Identifiers select context; no lexical match is treated as semantic coupling.
    tokens = {name: set(re.findall(r'[A-Za-z_]\w*', code)) for name, code in files.items()}
    def priority(name):
        return (name not in changed, -len(tokens[name] & changed_symbols), name)
    tests = sorted((name for name in files if is_test_path(name)), key=priority)
    production = sorted((name for name in files if not is_test_path(name)), key=priority)
    selected = tests[:budget.max_test_files] + production[:budget.max_production_files]
    selected.sort(key=priority)
    resolution, config_unknowns = module_configuration(repository) if language == 'typescript' else ({}, [])
    graph_files = dict(files)
    if language == 'go' and (repository/'go.mod').exists():
        graph_files['go.mod'] = (repository/'go.mod').read_text()
    dependencies = dependency_closure(graph_files, selected, language, max_additional=256, max_depth=4,
                                      **resolution)
    if language == 'go' and 'go.mod' in graph_files:
        module = re.search(r'(?m)^\s*module\s+(?:"([^"]+)"|([^\s]+))', graph_files['go.mod'])
        if module:
            resolution['go_modules'] = {'': module.group(1) or module.group(2)}
    selected.extend(path for path in dependencies['additional_paths'] if path in files and path not in selected)
    sources, size, metadata = [], 0, {}
    for name in selected:
        payload = files[name].encode()
        if size + len(payload) > budget.max_total_bytes:
            omitted.append({'path': name, 'reason': 'total_bytes'})
            continue
        source = Source(name, files[name], language)
        sources.append(source)
        size += len(payload)
        metadata[name] = {'kind': 'final_candidate_file', 'target_path': name,
                          'patch_changed': name in changed,
                          'relevance_symbols': sorted(tokens[name] & changed_symbols),
                          'sha256': hashlib.sha256(payload).hexdigest()}
    selected_paths = {source.path for source in sources}
    history, recovery = recover_history(json.loads(Path(case['trajectory']).read_text()), language)
    history_seen = {hashlib.sha256(source.data).hexdigest() for source in sources}
    # Newer source bodies are first; exact duplicate validation files add no evidence.
    for source in reversed(history):
        if source.language != language:
            continue
        if language == 'go' and (duplicates := go_duplicate_declarations(source)):
            omitted.append({'path': source.path, 'reason': 'duplicate_go_file_declarations',
                            'names': duplicates, 'step': source.step})
            continue
        digest = hashlib.sha256(source.data).hexdigest()
        if digest in history_seen or len(source.data) > budget.max_file_bytes:
            continue
        declared, _ = units(source)
        tests_here = [unit for unit in declared if unit.test]
        output_script = (source.language in {'python', 'typescript'} and any(
            node.type in {'call', 'call_expression'} and re.match(r'^(print\s*\(|console\.log\s*\(|assert\b)', source.text(node))
            for node in walk(source.root)))
        if not tests_here and not output_script:
            continue
        original = source.path
        target = _relative_written(source.written_path)
        # Distinct historical versions remain seeds, never overwrite final
        # code or count as current-version coverage.
        if target and target in files:
            final_source = Source(target, files[target], language)
            final_bodies = {final_source.text(u.node) for u in units(final_source)[0] if u.test}
            if tests_here and all(source.text(u.node) in final_bodies for u in tests_here):
                continue
        if sum(meta['kind'] == 'historical_validation' for meta in metadata.values()) >= budget.max_history_files:
            omitted.append({'path': original, 'reason': 'history_file_budget'})
            continue
        if size + len(source.data) > budget.max_total_bytes:
            omitted.append({'path': original, 'reason': 'total_bytes'})
            continue
        if target is None:
            if language == 'go':
                package = re.search(r'^\s*package\s+(\w+)', source.code, re.M)
                package_dirs = sorted({str(Path(name).parent) for name, code in files.items()
                                       if package and re.search(r'^\s*package\s+' + re.escape(package[1]) + r'\b', code, re.M)})
                if len(package_dirs) != 1:
                    omitted.append({'path': original, 'reason': 'historical_go_package_ambiguous'})
                    continue
                target = str(Path(package_dirs[0]) / ('zz_relational_history_' + digest[:12] + '_test.go'))
            elif language == 'python':
                target = 'test_relational_history_' + digest[:12] + '.py'
            else:
                # Relative imports need an original directory; do not guess it.
                omitted.append({'path': original, 'reason': 'historical_ts_target_unknown'})
                continue
        original_target = target
        original_name = Path(target)
        stem = original_name.stem
        if language == 'go':
            stem = stem.removesuffix('_test')
            target = str(original_name.with_name(stem + '_rh_' + digest[:12] + '_test.go'))
        elif language == 'python':
            target = str(original_name.with_name('test_rh_' + digest[:12] + '_' + original_name.name))
        else:
            recognized = re.search(r'(?:\.(?:unit\.)?(?:test|spec)|\.test-d)\.tsx?$', original_name.name)
            basename = original_name.name if recognized else stem + '.test.ts'
            target = str(original_name.with_name('rh_' + digest[:12] + '_' + basename))
        if target in selected_paths:
            continue
        # Import lookup is repository-relative. The original shell spelling
        # (possibly /app/... or /repo/...) remains in provenance below.
        relocated = Source(target, source.code, source.language, 'trajectory', source.step, original_target)
        renamed = []
        if language == 'go':
            relocated, renamed = namespace_go_validation(relocated, digest[:12])
        sources.append(relocated)
        selected_paths.add(target)
        history_seen.add(digest)
        size += len(source.data)
        metadata[target] = {'kind': 'historical_validation', 'target_path': target,
                            'original_target_path': original_target, 'relocated_globals': renamed,
                            'trajectory_source': original, 'step_id': source.step,
                            'original_written_path': source.written_path,
                            'sha256': digest, 'executed_on_final_candidate': False,
                            'requires_source_control_replay': True}
    sources.sort(key=lambda source: source.path)
    return sources, {'budget': asdict(budget), 'source_bytes': size, 'history_recovery': recovery,
                     'source_dependencies': dependencies,
                     'module_resolution': resolution, 'module_configuration_unknowns': config_unknowns,
                     'available_test_files': len(tests), 'available_production_files': len(production),
                     'selected_files': len(sources), 'changed_symbols': sorted(changed_symbols),
                     'files': metadata, 'omitted': omitted,
                     'test_file_budget_exhausted': len(tests) > budget.max_test_files,
                     'production_file_budget_exhausted': len(production) > budget.max_production_files,
                     'selection_only': True, 'uses_target_labels': False}
