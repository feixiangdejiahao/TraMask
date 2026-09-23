"""Transport path oracles through token-serialization contexts.

The IPython adapter identifies a command-string boundary, not a pilot/test name.
Both the path constructor and its serialization are rewritten; assertions retain
their original variable bindings. No repository code executes during generation.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path


def _loads(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)
            and isinstance(n.ctx, ast.Load)}


def _bound(node: ast.AST) -> set[str]:
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)
             and isinstance(n.ctx, ast.Store)}
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        names |= {a.arg for a in ast.walk(node.args) if isinstance(a, ast.arg)}
    return names


def _is_boundary(call: ast.AST) -> bool:
    # A language adapter: the argument positions of IPython's public interface.
    return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr in {'run_line_magic', 'run_cell_magic'}
            and len(call.args) >= 2)


def _interpolations(node: ast.AST, variable: str) -> list[ast.AST]:
    """Find a whole-token %s/f-string interpolation of a path variable."""
    found = []
    for part in ast.walk(node):
        if (isinstance(part, ast.BinOp) and isinstance(part.op, ast.Mod)
                and isinstance(part.left, ast.Constant)
                and isinstance(part.left.value, str)
                and part.left.value.count('%s') == 1
                and isinstance(part.right, ast.Name) and part.right.id == variable):
            before, after = part.left.value.split('%s')
            if (not before or before[-1].isspace()) and (not after or after[0].isspace()):
                found.append(part)
        elif isinstance(part, ast.JoinedStr):
            for i, value in enumerate(part.values):
                if (isinstance(value, ast.FormattedValue)
                        and isinstance(value.value, ast.Name)
                        and value.value.id == variable and value.format_spec is None):
                    left = part.values[i - 1] if i else None
                    right = part.values[i + 1] if i + 1 < len(part.values) else None
                    if ((left is None or isinstance(left, ast.Constant) and str(left.value)[-1:].isspace())
                            and (right is None or isinstance(right, ast.Constant) and str(right.value)[:1].isspace())):
                        found.append(value)
    return found


def _path_bindings(function: ast.FunctionDef) -> list[tuple[str, ast.Constant]]:
    found = []
    for node in ast.walk(function):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Div)
                and isinstance(node.value.right, ast.Constant)
                and isinstance(node.value.right.value, str)):
            found.append((node.targets[0].id, node.value.right))
    return found


def lift_path(function: ast.FunctionDef, variable: str, *, quote: str = '"') -> ast.FunctionDef:
    """Change a bound filename and quote each command token derived from it.

    A fixed whitespace witness is grammar based, not a learned bug input. Path
    expectations expressed using the binding are transported automatically.
    """
    result = copy.deepcopy(function)
    bindings = dict(_path_bindings(result))
    literal = bindings[variable]
    value = literal.value
    if not isinstance(value, str) or any(c in value for c in '\\/' + quote + '\n\r'):
        raise ValueError('Only a single quote-free filename component is supported')
    # Reassignments make this simple binding transport ambiguous.
    stores = [n for n in ast.walk(result) if isinstance(n, ast.Name)
              and n.id == variable and isinstance(n.ctx, ast.Store)]
    if len(stores) != 1:
        raise ValueError('Path binding is reassigned')
    # A literal expected filename would need a separate oracle rewrite.
    for assertion in (n for n in ast.walk(result) if isinstance(n, ast.Assert)):
        if any(isinstance(n, ast.Constant) and n.value == value for n in ast.walk(assertion)):
            raise ValueError('Oracle freezes the original filename as a literal')
    literal.value = 'cc space ' + value
    changed = 0
    for call in (n for n in ast.walk(result) if _is_boundary(n)):
        for expression in _interpolations(call.args[1], variable):
            if isinstance(expression, ast.BinOp):
                expression.left.value = expression.left.value.replace('%s', quote + '%s' + quote)
            else:
                expression.value = ast.BinOp(
                    left=ast.BinOp(left=ast.Constant(quote), op=ast.Add(),
                                   right=ast.Call(func=ast.Name(id='str', ctx=ast.Load()),
                                                  args=[expression.value], keywords=[])),
                    op=ast.Add(), right=ast.Constant(quote))
            changed += 1
    if not changed:
        raise ValueError('No whole-token path interpolation at a supported command boundary')
    return ast.fix_missing_locations(result)


def _support(module: ast.Module, functions: list[ast.FunctionDef]) -> list[ast.stmt]:
    """Retain transitive imports/helpers/constants/fixtures needed by clones."""
    definitions: dict[str, ast.stmt] = {}
    for stmt in module.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[stmt.name] = stmt
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                definitions[alias.asname or alias.name.split('.')[0]] = stmt
        else:
            for name in _bound(stmt):
                definitions[name] = stmt
    required = set()
    for fn in functions:
        required |= _loads(fn) - _bound(fn)
        # Named pytest fixtures are dependencies even though parameters bind them.
        required |= {arg.arg for arg in fn.args.args}
    selected: set[int] = set()
    pending = list(required)
    while pending:
        name = pending.pop()
        stmt = definitions.get(name)
        if stmt is None or id(stmt) in selected:
            continue
        selected.add(id(stmt))
        pending.extend(_loads(stmt) - _bound(stmt))
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pending.extend(arg.arg for arg in stmt.args.args)
    result = []
    for stmt in module.body:
        if isinstance(stmt, ast.ImportFrom) and stmt.module == '__future__':
            result.append(copy.deepcopy(stmt))
        elif id(stmt) in selected:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                # Only necessary aliases, not unrelated implementation constants.
                needed_names = set(required)
                for other in module.body:
                    if id(other) in selected and not isinstance(other, (ast.Import, ast.ImportFrom)):
                        needed_names |= _loads(other)
                cloned = copy.deepcopy(stmt)
                cloned.names = [a for a in cloned.names
                                if (a.asname or a.name.split('.')[0]) in needed_names]
                if cloned.names:
                    result.append(cloned)
            else:
                result.append(copy.deepcopy(stmt))
    return result


def generate_paths(repository: Path, selection: dict, *, top_k: int = 10) -> dict:
    """Return new test files and provenance; no evaluator information is read."""
    files: dict[str, str] = {}
    obligations = []
    skipped = []
    grouped: dict[str, list[dict]] = {}
    for seed in selection['selected_tests'][:top_k]:
        grouped.setdefault(seed['path'], []).append(seed)
    for relative, seeds in grouped.items():
        source = repository / relative
        if not source.is_file() or source.suffix != '.py':
            continue
        module = ast.parse(source.read_text())
        functions = {f.name: f for f in module.body if isinstance(f, ast.FunctionDef)}
        generated = []
        for seed in seeds:
            function = functions.get(seed['name'])
            if function is None:
                continue
            for variable, literal in _path_bindings(function):
                digest = hashlib.sha256(f'{relative}:{function.name}:{variable}'.encode()).hexdigest()[:12]
                variants = []
                for quote, label in [('"', 'double'), ("'", 'single')]:
                    try:
                        lifted = lift_path(function, variable, quote=quote)
                    except ValueError as error:
                        skipped.append({'seed': seed['test_id'], 'variable': variable,
                                        'reason': str(error)})
                        continue
                    lifted.name = f'test_cc_path_{digest}_{label}'
                    variants.append(lifted)
                    obligations.append({'test': lifted.name, 'seed': seed['test_id'],
                                        'seed_rank': seed['rank'], 'path': relative,
                                        'binding_line': literal.lineno, 'variable': variable,
                                        'operation': 'path_whitespace_and_token_quote',
                                        'quote': quote, 'oracle': 'transport_original_bindings',
                                        'control': f'test_cc_path_{digest}_control'})
                if variants:
                    control = copy.deepcopy(function)
                    control.name = f'test_cc_path_{digest}_control'
                    generated.extend([control, *variants])
        if generated:
            output = ast.fix_missing_locations(ast.Module(body=[*_support(module, generated), *generated], type_ignores=[]))
            file_id = hashlib.sha256(relative.encode()).hexdigest()[:8]
            target = str(Path(relative).parent / f'test_cc_paths_{file_id}.py')
            files[target] = '# Automatically generated by path context transport.\n' + ast.unparse(output) + '\n'
    return {'files': files, 'obligations': obligations, 'skipped': skipped,
            'generator': 'path_context_transport', 'external_model_calls': 0}
