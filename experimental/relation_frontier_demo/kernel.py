"""Small, trusted-code-only relation-profile search; no oracle generation."""
import argparse
import ast
import collections
import copy
import hashlib
import inspect
import io
import json
import math
from pathlib import Path
import sys
from contextlib import redirect_stdout, redirect_stderr


def numeric(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def position(node):
    return [node.lineno, node.col_offset]


def constant(value):
    return ast.parse(repr(value), mode="eval").body


def literals(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return ...


def prepare(source, filename):
    tree = ast.parse(source, filename)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    seeds = []
    for test in functions.values():
        if not test.name.startswith("test_") or test.args.args:
            continue
        for call in ast.walk(test):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            target = functions.get(call.func.id)
            if target is None or target.name.startswith("test_"):
                continue
            values = [literals(a) for a in call.args]
            kw = {k.arg: literals(k.value) for k in call.keywords if k.arg is not None}
            if any(v is ... for v in [*values, *kw.values()]) or len(kw) != len(call.keywords):
                continue
            seeds.append(dict(test=test.name, target=target.name, call=call,
                              args=values, kwargs=kw))
    descriptors = {}
    for seed in seeds:
        name = seed["target"]
        if name in descriptors:
            continue
        target = functions[name]
        anchors, keys, pools = [], set(), collections.defaultdict(list)
        locations = [dict(kind="parameter", slot=i, at=position(a)) for i, a in enumerate(target.args.args)]
        for node in ast.walk(target):
            if isinstance(node, ast.Compare):
                for term in [node.left, *node.comparators]:
                    value = literals(term)
                    if numeric(value) and value not in anchors:
                        anchors.append(value)
                        locations.append(dict(kind="comparison_anchor", at=position(term), value=value))
            key, default = ..., ...
            if isinstance(node, ast.Subscript):
                key = literals(node.slice)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "get" and node.args:
                    key = literals(node.args[0])
                    default = literals(node.args[1]) if len(node.args) > 1 else None
            if type(key) is str:
                keys.add(key)
                locations.append(dict(kind="mapping_key", at=position(node), value=key))
                if default is not ...:
                    pools[key].append(default)
        for item in (s for s in seeds if s["target"] == name):
            for value in [*item["args"], *item["kwargs"].values()]:
                if type(value) is dict:
                    for key, child in value.items():
                        if type(key) is str:
                            keys.add(key)
                            pools[key].append(child)
                            locations.append(dict(kind="seed_mapping_key", at=position(item["call"]), value=key))
        descriptors[name] = dict(parameters=[a.arg for a in target.args.args],
                                 anchors=anchors, keys=sorted(keys), pools=dict(pools),
                                 term_sources=locations)
    return tree, seeds, descriptors


def profile(bound, desc):
    # Argument slot and anchor ordinal survive identifier renaming and translation.
    nums = [(f"arg:{i}", bound.get(name)) for i, name in enumerate(desc["parameters"])
            if numeric(bound.get(name))]
    nums += [(f"anchor:{i}", a) for i, a in enumerate(desc["anchors"])]
    order = [(a, b, (x > y) - (x < y)) for i, (a, x) in enumerate(nums)
             for b, y in nums[i + 1:]]
    masks = [(f"arg:{i}", [key in bound[name] for key in desc["keys"]])
             for i, name in enumerate(desc["parameters"]) if type(bound.get(name)) is dict]
    return dict(order=order, joint_presence=masks)


def mutations(args, kwargs, desc):
    numeric_values = [v for v in [*args, *kwargs.values()] if numeric(v)] + desc["anchors"]
    for kind, items in [("args", list(enumerate(args))), ("kwargs", list(kwargs.items()))]:
        for slot, value in items:
            alternatives = []
            if numeric(value):
                alternatives = [(v + delta, "numeric_neighbor")
                                for v in numeric_values for delta in (0, -1, 1)]
            elif type(value) is dict:
                for key in sorted(value, key=repr):
                    new = dict(value)
                    del new[key]
                    alternatives.append((new, f"delete_key:{key}"))
                for key in desc["keys"]:
                    if key not in value:
                        for item in desc["pools"].get(key, [])[:2]:
                            alternatives.append(({**value, key: item}, f"add_key:{key}"))
            for new, operation in alternatives:
                if new == value:
                    continue
                updated_args, updated_kw = copy.deepcopy(args), copy.deepcopy(kwargs)
                (updated_args if kind == "args" else updated_kw)[slot] = new
                yield updated_args, updated_kw, dict(kind=operation, port=[kind, slot], before=repr(value), after=repr(new))


def execute(tree, filename, seed, args, kwargs, desc):
    module = copy.deepcopy(tree)
    assertions, outcomes, lines, bound = [], [], set(), {}
    active = False
    entered = False
    finished = False
    call_pos = position(seed["call"])

    class Edit(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            return self.generic_visit(node) if node.name == seed["test"] else node

        def visit_Call(self, node):
            self.generic_visit(node)
            if position(node) == call_pos and isinstance(node.func, ast.Name) and node.func.id == seed["target"]:
                node.args = [ast.copy_location(constant(v), node) for v in args]
                node.keywords = [ast.keyword(arg=k, value=constant(v)) for k, v in kwargs.items()]
                return ast.copy_location(ast.Call(ast.Name("_rf_invoke", ast.Load()), [node.func, *node.args], node.keywords), node)
            return node

        def visit_Assert(self, node):
            self.generic_visit(node)
            node.test = ast.copy_location(ast.Call(ast.Name("_rf_assert", ast.Load()),
                                                  [node.test, constant(position(node))], []), node.test)
            return node

    module = ast.fix_missing_locations(Edit().visit(module))

    def invoke(fn, *aa, **kk):
        nonlocal active, finished
        active = True
        try:
            value = fn(*aa, **kk)
            outcomes.append(repr(value))
            return value
        finally:
            active = False
            finished = True

    def check(value, at):
        truth = bool(value)
        assertions.append(dict(at=at, passed=truth, after_selected_call=finished))
        return truth

    def trace(frame, event, arg):
        nonlocal entered
        if active and frame.f_code.co_filename == filename and frame.f_code.co_name == seed["target"]:
            if event == "line":
                lines.add(frame.f_lineno)
            if event == "call" and not entered:
                entered = True
                bound.update({p: copy.deepcopy(frame.f_locals[p]) for p in desc["parameters"] if p in frame.f_locals})
        return trace

    namespace = {"_rf_invoke": invoke, "_rf_assert": check}
    previous = sys.gettrace()
    status, error = "pass", None
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            exec(compile(module, filename, "exec"), namespace)
            inspect.signature(namespace[seed["target"]]).bind(*args, **kwargs)
            sys.settrace(trace)
            namespace[seed["test"]]()
        except AssertionError as exc:
            status = "assertion_failure" if assertions and not assertions[-1]["passed"] else "execution_error"
            error = f"AssertionError: {exc}"
        except Exception as exc:
            status, error = "execution_error", f"{type(exc).__name__}: {exc}"
        finally:
            sys.settrace(previous)
    return dict(profile=profile(bound, desc), entered_target=entered,
                target_lines=sorted(lines), assertions=assertions,
                source_assertion_evaluated=any(a["after_selected_call"] for a in assertions), status=status,
                error=error, captured_actual=outcomes)


def run(source, filename="<input>", budget=80, representatives=2):
    tree, seeds, descriptors = prepare(source, filename)
    queue, seen, buckets, covered, results = collections.deque(), set(), collections.Counter(), {}, []
    for index, seed in enumerate(seeds):
        queue.append((index, seed["args"], seed["kwargs"], None, None))
    while queue and len(results) < budget:
        index, args, kwargs, parent, edit = queue.popleft()
        seed, desc = seeds[index], descriptors[seeds[index]["target"]]
        signature = (index, repr(args), repr(kwargs))
        if signature in seen:
            continue
        seen.add(signature)
        observation = execute(tree, filename, seed, args, kwargs, desc)
        pkey = (seed["target"], json.dumps(observation["profile"], sort_keys=True))
        prior_lines = covered.setdefault(seed["target"], set())
        new_lines = sorted(set(observation["target_lines"]) - prior_lines)
        prior_lines.update(observation["target_lines"])
        new_profile = observation["entered_target"] and buckets.get(pkey, 0) == 0
        keep = observation["entered_target"] and buckets.get(pkey, 0) < representatives
        row = dict(id=len(results), seed_index=index, source_test=seed["test"],
                   target=seed["target"], source_call=position(seed["call"]),
                   arguments=args, keywords=kwargs, parent=parent, edit=edit,
                   new_profile=new_profile, new_target_lines=new_lines,
                   retained_for_expansion=keep, **observation)
        results.append(row)
        if keep:
            buckets[pkey] += 1
            for aa, kk, mutation in mutations(args, kwargs, desc):
                kind, slot = mutation["port"]
                node = seed["call"].args[slot] if kind == "args" else next(k.value for k in seed["call"].keywords if k.arg == slot)
                mutation["at"] = position(node)
                queue.append((index, aa, kk, row["id"], mutation))
    collisions = []
    for i, left in enumerate(results):
        for right in results[:i]:
            if (left["target"] == right["target"] and left["profile"] == right["profile"]
                    and left["captured_actual"] != right["captured_actual"]
                    and left["captured_actual"] and right["captured_actual"]):
                collisions.append([right["id"], left["id"]])
                break
    return dict(source_sha256=hashlib.sha256(source.encode()).hexdigest(), budget=budget,
                bounded_heuristic=True, representatives_per_profile=representatives,
                extracted=descriptors, seed_count=len(seeds), executed=len(results),
                profiles=len(buckets), same_profile_different_actual=collisions, results=results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--budget", type=int, default=80)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    options.output.write_text(json.dumps(run(options.source.read_text(), str(options.source), options.budget), indent=2) + "\n")
