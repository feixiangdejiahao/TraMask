"""Recover omitted, explicitly referenced source declarations without a repo walk.

The frozen corpus is authoritative: existing source text is never replaced by
filesystem text. Only imports/reexports, Python package initializers, and Go
package scope select additional ordinary source files. This is context recovery,
not proof of loading, build selection, a public contract, or test validity.
"""
from __future__ import annotations

from collections import deque
import hashlib
from pathlib import Path
import posixpath
import re

from relational_gap.source_dependencies import _imports, _python_paths, _ts_paths


VERSION = 'candidate_source_dependencies.v1'
SOURCE_SUFFIXES = {'.py', '.go', '.ts', '.tsx', '.mts', '.cts', '.js', '.jsx'}
EXCLUDED_PARTS = {'.git', '.venv', 'node_modules', '__pycache__', 'hidden_verifier',
                  'hidden_tests', 'reference_patch', 'reference_implementation'}


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


class _Files(dict):
    """Resolve exact proposed paths lazily; membership never reads file content."""
    def __init__(self, root, sources):
        super().__init__((p,row['code']) for p,row in sources.items())
        self.root = root

    def path(self, name):
        relative = Path(name)
        if relative.is_absolute() or any(part in EXCLUDED_PARTS for part in relative.parts):
            return None
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root) or target.suffix not in SOURCE_SUFFIXES:
            return None
        return target if target.is_file() else None

    def __contains__(self, name):
        return super().__contains__(name) or self.path(name) is not None

    def read(self, name):
        if dict.__contains__(self, name):
            return dict.__getitem__(self, name)
        target = self.path(name)
        if target is None:
            raise FileNotFoundError(name)
        return target.read_text(encoding='utf-8')


def _package(code):
    match = re.search(r'(?m)^\s*package\s+([A-Za-z_]\w*)\s*(?:;|$)', code)
    return match.group(1) if match else None


def enrich_sources(corpus, frontend, repository, candidates=(), *, max_added_files=256, max_depth=8):
    """Return ``(new_corpus, provenance)`` without changing any frozen source.

    Filesystem access is bounded to exact proposed import paths and directories
    containing an existing Go package. No provider, verifier, or subprocess is
    consulted. Generated import aliases contribute their donor-relative module
    references, independently of candidate labels or execution results.
    """
    if type(max_added_files) is not int or type(max_depth) is not int or min(max_added_files,max_depth) < 0:
        raise ValueError('source dependency bounds must be nonnegative integers')
    root = Path(repository).resolve(strict=True)
    language = corpus['language']
    if language not in {'python','typescript','go'}:
        raise ValueError('source dependency recovery requires one supported language')
    sources = dict(corpus['sources'])
    files = _Files(root, sources)
    resolution = frontend.get('module_resolution', {})
    aliases = {pattern:([targets] if isinstance(targets,str) else targets)
               for pattern,targets in (resolution.get('aliases') or {}).items()}
    queue = deque((path,0) for path in sorted(sources))
    seen, packages, added, edges, unknowns = set(), set(), [], [], []
    budget_exhausted = depth_exhausted = False

    def include(owner, target, depth, kind, module=None):
        nonlocal budget_exhausted
        if target in sources:
            return
        if len(added) >= max_added_files:
            budget_exhausted = True
            unknowns.append(dict(path=owner,target=target,reason='source_file_budget'))
            return
        try:
            code = files.read(target)
        except (FileNotFoundError, OSError, UnicodeError) as error:
            unknowns.append(dict(path=owner,target=target,reason='source_read_failed',detail=type(error).__name__))
            return
        sources[target] = dict(code=code,language=language,origin='repository',
                               written_path=target,step=None)
        files[target] = code
        record = dict(path=target,source_sha256=_hash(code),introduced_by=owner,kind=kind,
                      module=module,depth=depth+1)
        added.append(record)
        edges.append(dict(source=owner,target=target,kind=kind,module=module))
        queue.append((target,depth+1))

    def go_directory(owner, directory, depth, kind):
        """Package members are a lexical dependency, not a same-name guess."""
        package = _package(sources[owner]['code']) if kind == 'package_scope' else None
        key = directory,package
        if key in packages:
            return
        packages.add(key)
        candidate_dir = (root / directory).resolve()
        if not candidate_dir.is_relative_to(root) or not candidate_dir.is_dir():
            return
        for path in sorted(candidate_dir.glob('*.go')):
            if path.name.endswith('_test.go'):
                continue
            relative = path.relative_to(root).as_posix()
            if files.path(relative) is None or relative in sources:
                continue
            if len(added) >= max_added_files:
                include(owner,relative,depth,kind)
                continue
            try:
                code = files.read(relative)
            except (OSError,UnicodeError):
                continue
            if package is None or _package(code) == package:
                include(owner,relative,depth,kind,directory)

    modules = dict(resolution.get('go_modules') or {})
    # Only metadata at known package ancestors is inspected; no directory tree
    # scan is required to recover a nested Go module.
    if language == 'go':
        for path,row in sorted(sources.items()):
            lookup = row.get('written_path') or path
            directory = Path(lookup).parent
            for ancestor in [directory,*directory.parents]:
                if ancestor.is_absolute() or '..' in ancestor.parts:
                    continue
                manifest = (root/ancestor/'go.mod').resolve()
                if not manifest.is_relative_to(root) or not manifest.is_file():
                    continue
                code = manifest.read_text(encoding='utf-8')
                match = re.search(r'(?m)^\s*module\s+(?:"([^"]+)"|([^\s]+))',code)
                if match:
                    modules[ancestor.as_posix() if ancestor.as_posix() != '.' else ''] = match.group(1) or match.group(2)
                break

    generated = {}
    for candidate in candidates:
        for record in candidate.get('imports',[]):
            owner = record.get('source_path') or corpus['tests'][candidate['base_test_id']]['span']['path']
            generated.setdefault(owner,[]).append(dict(module=record['module'],kind='generated_import',
                members=[record['imported_name']] if record.get('imported_name') else [],
                level=len(record['module'])-len(record['module'].lstrip('.')) if language == 'python' else 0))
    while queue:
        path,depth = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        if depth >= max_depth:
            depth_exhausted = True
            continue
        lookup = sources[path].get('written_path') or path
        imports,error = _imports(lookup,sources[path]['code'],language)
        if error:
            unknowns.append(dict(path=path,reason=error))
        imports.extend(generated.get(path,[]))
        if language == 'go':
            go_directory(path,posixpath.dirname(lookup),depth,'package_scope')
        for dependency in imports:
            module = dependency['module']
            if language == 'typescript':
                targets,reason = _ts_paths(files,lookup,module,aliases,resolution.get('base_url'))
            elif language == 'python':
                module = module.lstrip('.')
                targets,reason = _python_paths(files,lookup,module,dependency['level'],dependency['members'])
            else:
                matches = [(prefix,base) for base,prefix in modules.items()
                           if module == prefix or module.startswith(prefix+'/')]
                for prefix,base in sorted(matches,key=lambda row:(-len(row[0]),row[1])):
                    directory = posixpath.normpath(posixpath.join(base,module[len(prefix):].lstrip('/')))
                    go_directory(path,'' if directory == '.' else directory,depth,'imported_package_scope')
                if not matches:
                    unknowns.append(dict(path=path,module=module,reason='external_or_missing_go_module'))
                continue
            if not targets:
                unknowns.append(dict(path=path,module=module,reason=reason))
            for target in targets:
                include(path,target,depth,dependency['kind'],module)
    result = dict(corpus,sources=sources)
    provenance = dict(version=VERSION,repository=str(root),added=added,edges=edges,unknowns=unknowns,
        limits=dict(max_added_files=max_added_files,max_depth=max_depth,budget_exhausted=budget_exhausted,
                    depth_limit_reached=depth_exhausted),
        frozen_source_count=len(corpus['sources']),enriched_source_count=len(sources),
        interpretation='Explicit source context dependencies, not normative specifications or execution proof.')
    return result,provenance
