"""Search for missing joint checks in connected program behavior.

The finite dimensions come from source operations. Relations constrain where
to combine them; test rows supply evidence, not a universal coverage proof.
Single- and multi-relation candidates use the same representation and queue.
"""
from __future__ import annotations

from collections import defaultdict, deque
from itertools import combinations, product
import re

from .program import stable_id, reachable
from .scopes import test_scope
from .ranking import rank_candidates


def bounded_candidates(candidates, limit, *, issue=""):
    return rank_candidates(candidates, issue, limit=limit)[0]


def _dimension(kind, expression, node, domain, **extra):
    return {"id": "condition_" + stable_id(kind, expression, node["function_id"], extra),
            "kind": kind, "expression": expression, "function_id": node["function_id"],
            "span": node["span"], "domain": domain, "execution_context": node.get("conditions", []), **extra}


def _linked_nodes(graph, seeds, *, limit=60, depth=3):
    adjacent = graph.get("_adjacent")
    if adjacent is None:
        adjacent = defaultdict(set)
        for edge in graph["edges"]:
            adjacent[edge["from"]].add(edge["to"])
            adjacent[edge["to"]].add(edge["from"])
        graph["_adjacent"] = dict(adjacent)
    seen, pending = set(), deque((seed, 0) for seed in seeds)
    while pending and len(seen) < limit:
        item, distance = pending.popleft()
        if item in seen or item not in graph["nodes"]:
            continue
        seen.add(item)
        if distance < depth:
            pending.extend((n, distance + 1) for n in sorted(adjacent.get(item, [])) if n not in seen)
    return seen


def _combinations(dimensions, scope, *, max_order=3, limit=40):
    """Enumerate local cells. Unknown source evidence never counts as coverage."""
    missing, checked, unknown = [], [], []
    dims = dimensions[:8]
    groups = [tuple(dims)] if len(dims) <= max_order else [group for size in range(2, max_order + 1) for group in combinations(dims, size)]
    if not dims:
        return {"missing": [], "checked": [], "unknown": [], "truncated": False}
    total, exhausted = 0, False
    for group in groups:
        # A source predicate's domain has no claim that both sides are feasible.
        for values in product(*(d["domain"] for d in group)):
            total += 1
            condition = {d["id"]: value for d, value in zip(group, values)}
            matches, possible = [], []
            for row in scope["rows"]:
                observed = row["conditions"]
                if any(observed.get(key, {}).get("known") and observed[key]["value"] != value for key, value in condition.items()):
                    continue
                opaque_phase = any(c["value"] is None for d in group for c in d.get("execution_context", []))
                barriers = any(observed.get(key, {}).get("control_barriers") for key in condition)
                if all(observed.get(key, {}).get("known") for key in condition) and row["assertions"] and not row["source_conditions"] and not opaque_phase and not barriers:
                    matches.append(row["id"])
                else:
                    possible.append(row["id"])
            cell = {"conditions": condition, "source_witnesses": matches, "unresolved_rows": possible[:8]}
            if matches:
                checked.append(cell)
            elif possible or scope["truncated"]:
                unknown.append(cell)
            else:
                missing.append(cell)
            if total >= limit:
                exhausted = True
                break
        if exhausted:
            break
    return {"missing": missing, "checked": checked, "unknown": unknown, "truncated": exhausted or len(dimensions) > 8,
            "meaning": "A witnessed cell has one concrete source check, not proof that all values or assertions are adequate."}


def search_joint(program, graph, *, resources=None, max_order=3, max_candidates=160, issue=""):
    if not 1 <= max_order <= 4:
        raise ValueError("max_order_must_be_between_one_and_four")
    if max_candidates < 1:
        raise ValueError("max_candidates_must_be_positive")
    nodes = graph["nodes"]
    edges = graph["edges"]
    seeds = []

    def propose(family, operations, dimensions, question, *, links=None, declaration=None, transfer=None, priority=2):
        operations = list(dict.fromkeys(operations))
        if not operations:
            return
        if not any(nodes[n]["changed"] or nodes[n]["function_id"] in program["changed"] for n in operations):
            nearby = _linked_nodes(graph, operations, depth=2)
            if not any(nodes[n]["changed"] for n in nearby):
                return
        selected = _linked_nodes(graph, operations, limit=45, depth=2)
        selected.update(operations)
        actual_links = links or [e for e in edges if e["from"] in selected and e["to"] in selected]
        seed = {"family": family, "operations": operations, "selected": sorted(selected), "dimensions": dimensions,
                "question": question, "relations": actual_links, "declaration": declaration, "transfer": transfer, "priority": priority}
        seed["key"] = stable_id(family, operations, [d["id"] for d in dimensions], declaration)
        seeds.append(seed)

    # Joint predicate outcomes are considered even when each branch already has a witness.
    for fid, ids in graph["by_function"].items():
        guards = [nodes[n] for n in ids if nodes[n]["kind"] == "condition"]
        for guard in guards:
            dims = [_dimension("predicate", atom["expression"], {**guard, "span": atom["span"]}, [False, True]) for atom in guard["atoms"]]
            if len(dims) > 1:
                propose("joint_conditions", [guard["id"]], dims,
                        "这些条件共同影响哪个结果？原测试是否在同一次调用中检查了相关组合？", priority=3)
        # Conditions connected through a state/value operation form a local region.
        for operation in [nodes[n] for n in ids if nodes[n]["changed"] and nodes[n]["kind"] in {"assignment", "observation"}]:
            linked = _linked_nodes(graph, [operation["id"]], limit=35, depth=2)
            connected = [g for g in guards if g["id"] in linked]
            dims = {stable_id(a["expression"], fid): _dimension("predicate", a["expression"], {**g, "span": a["span"]}, [False, True])
                    for g in connected for a in g["atoms"]}
            if len(dims) > 1:
                propose("joint_conditions", [operation["id"]] + [g["id"] for g in connected], list(dims.values()),
                        "这些相连条件对该结果的联合影响是否得到检查？已有单项检查不代表联合检查。", priority=4)

    for default in graph["defaults"]:
        origin = nodes[default["operation"]]
        consumers = [nodes[n] for n in graph["by_function"][default["function_id"]]
                     if nodes[n]["kind"] == "call" and default["root"] in nodes[n]["arguments"]
                     and nodes[n]["span"]["start_byte"] > origin["span"]["start_byte"]]
        if not consumers:
            continue
        path = default["root"] + "." + default["field"]
        dims = [_dimension("presence", path + " 是否显式提供", origin, [False, True], access=path)]
        operations = [origin["id"]] + [n["id"] for n in consumers]
        downstream = []
        for consumer in consumers:
            for target in consumer["targets"]:
                for n in graph["by_function"].get(target, []):
                    node = nodes[n]
                    if node["kind"] == "condition" and (default["field"] in node["code"] or any(default["field"] in r.split(".") for r in node["reads"])):
                        downstream.append(n)
                        for atom in node["atoms"]:
                            dims.append(_dimension("predicate", atom["expression"], {**node, "span": atom["span"]}, [False, True]))
        propose("default_propagation", operations + downstream, dims,
                "局部默认化后，下游仍收到原对象。省略字段与显式默认值在需求上是否应保持相同行为？",
                transfer={"input_access": path, "local_binding": default["local"], "default_literal": default["default"],
                          "assignment": origin["span"], "forwarded_argument": default["root"],
                          "consumer_operations": [n["id"] for n in consumers], "downstream_guards": downstream,
                          "meaning": "The default is assigned locally. The shown calls forward the original object; this does not establish that no intervening write changed it."}, priority=0)

    blocked = defaultdict(list)
    for edge in edges:
        if edge["kind"] == "may_prevent_continuation":
            blocked[edge["from"]].append(edge)
    for exit_id, links in blocked.items():
        exit_node = nodes[exit_id]
        later = sorted({e["to"] for e in links}, key=lambda x: nodes[x]["span"]["start_byte"])
        dims = []
        for condition in exit_node["conditions"]:
            if condition["value"] is not None:
                dims.append(_dimension("predicate", condition["expression"], {**exit_node, "span": condition["span"]}, [False, True]))
        for node_id in later:
            for condition in nodes[node_id]["conditions"]:
                if condition["value"] is not None:
                    dims.append(_dimension("predicate", condition["expression"], {**nodes[node_id], "span": condition["span"]}, [False, True]))
        dims = list({d["id"]: d for d in dims}.values())
        propose("blocked_continuation", [exit_id] + later[:8], dims,
                "退出条件与后续操作共同使用时，需求是否仍要求该操作的结果？操作被生产代码跳过本身可能是错误。",
                links=links[:8], priority=0)

    for fid, ids in graph["by_function"].items():
        lookups = [nodes[n] for n in ids if nodes[n]["kind"] == "lookup"]
        returns = [nodes[n] for n in ids if nodes[n]["kind"] == "observation" and nodes[n].get("conditions")]
        if not lookups or not returns:
            continue
        for lookup in lookups[:4]:
            location = (lookup.get("container") or "container") + "." + lookup.get("key", "key").strip("'\"")
            dims = [_dimension("presence", "位置或键是否存在: " + location, lookup, [False, True], access=location),
                    _dimension("value_category", "存在位置的读取值: " + location, lookup, ["ordinary", "undefined", "null"], access=location)]
            propose("lookup_presence", [lookup["id"]] + [r["id"] for r in returns], dims,
                    "读取过程可能合并缺失与已有值。下游需求是否需要区分存在性和读取值？", priority=1)

    for allocation in graph["allocations"]:
        node = nodes[allocation]
        dims = [_dimension("sharing", "不同输入项是否引用同一存储", node, ["distinct", "shared"]),
                _dimension("phase", "观察复制前或复制后共享状态", node, ["before", "after_write_then_read"])]
        propose("shared_copy", [allocation], dims,
                "循环为各项创建新存储。如果不同项原先共享状态，需求是否要求在复制后保留该共享关系？", priority=0)

    # Symbol links expose compiler/interpreter evidence without claiming emitted instructions ran.
    for edge in edges:
        if edge["kind"] == "symbol_dispatch" and nodes[edge["from"]]["changed"]:
            handler = nodes[edge["to"]]
            dims = [_dimension("phase", "同一指令的生成与执行", handler, ["generated", "executed_with_boundary_input"])]
            calls = [nodes[n] for n in graph["by_function"][handler["function_id"]] if nodes[n]["kind"] == "call"
                     and handler["span"]["start_byte"] <= nodes[n]["span"]["start_byte"] < handler["span"]["end_byte"]]
            calls.sort(key=lambda n: (not bool(n["targets"]), n["span"]["start_byte"]))
            propose("dispatch_flow", [edge["from"], edge["to"]] + [n["id"] for n in calls[:6]], dims,
                    "生成的指令会进入此执行分支。原验证是否通过公开入口检查了执行语义及边界状态？", links=[edge], priority=1)

    state_groups = defaultdict(list)
    for edge in edges:
        if edge["kind"] == "shared_state":
            key = (edge["resource"], nodes[edge["from"]]["function_id"], nodes[edge["to"]]["function_id"])
            state_groups[key].append(edge)
    for (resource, _, _), links in state_groups.items():
        links = sorted(links, key=lambda e: (not nodes[e["from"]]["changed"], not nodes[e["to"]]["changed"], e["from"], e["to"]))
        operations = list(dict.fromkeys(x for e in links for x in (e["from"], e["to"])))
        node = nodes[operations[0]]
        dims = [_dimension("phase", "同一状态的观察阶段: " + resource, node, ["after_write", "after_consumer"])]
        propose("state_continuation", operations[:12], dims,
                "原检查停在哪个阶段？同一对象进入这些后续消费者后，需求是否还要求保持或更新该结果？",
                links=links[:16], priority=1)

    if resources:
        from .relations import schema_constraints
        constraints = schema_constraints(resources)
        normalized = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())
        field_uses = defaultdict(set)
        for node in nodes.values():
            if node["kind"] not in {"call", "assignment", "condition"}:
                continue
            for value in node["reads"] + node.get("input_origin_reads", []):
                parts = [normalized(x) for x in value.split(".")]
                if len(parts) >= 2:
                    field_uses[tuple(parts[-2:])].add(node["id"])
        for declaration in constraints:
            path = declaration["field_path"].split(".")
            if not path or not path[-1]:
                continue
            tail = tuple(normalized(x) for x in path[-2:])
            matches = field_uses.get(tail, [])
            if not matches:
                continue
            def field_match_length(operation):
                best = 0
                for value in nodes[operation]["reads"] + nodes[operation].get("input_origin_reads", []):
                    common = 0
                    for a, b in zip(reversed(path), reversed(value.split("."))):
                        if normalized(a) != normalized(b):
                            break
                        common += 1
                    best = max(best, common)
                return best
            operations = sorted(matches, key=lambda n: (-field_match_length(n), not nodes[n]["changed"], n))[:12]
            node = nodes[operations[0]]
            dims = [_dimension("phase", "同一字段经过声明校验与运行处理: " + declaration["field_path"], node,
                               ["runtime_only", "declaration_then_runtime"])]
            propose("declaration_flow", operations, dims,
                    "字段路径提示这些处理可能受同一声明约束。它们是否对应同一公开入口及需求？补测须经过真实入口校验。",
                    declaration=declaration, priority=0)

    unique = {s["key"]: s for s in seeds}
    # Rank before the expensive test-scope expansion as well as before LLM calls.
    # The same source evidence guides both bounds; no reference targets are read.
    seed_views = [{"id": s["key"], "relations": s["relations"], "evidence": {"source_operations": s["operations"]},
                   "behavior": {"operations": [nodes[n] for n in s["operations"]], "conditions": s["dimensions"], "default_transfer": s["transfer"]}}
                  for s in unique.values()]
    selected_seeds, ranking = rank_candidates(seed_views, issue, limit=max_candidates)
    ordered = [unique[s["id"]] for s in selected_seeds]
    candidates = []
    for seed in ordered[:max_candidates]:
        operations = [nodes[n] for n in seed["selected"]]
        fids = sorted({n["function_id"] for n in operations})
        dimensions = list({d["id"]: d for d in seed["dimensions"]}.values())
        condition_functions = {d["function_id"] for d in dimensions}
        scope = test_scope(program, graph, condition_functions or fids, dimensions)
        cells = _combinations(dimensions, scope, max_order=max_order)
        relevant_tests = set(scope["test_ids"])
        relevant_tests.update(c["test_id"] for c in program["calls"] if set(c["targets"]) & set(fids))
        observations = [n for n in operations if n["kind"] == "observation"]
        relation_count = len({(e["from"], e["to"], e["kind"]) for e in seed["relations"]})
        row = {"id": "joint_" + seed["key"], "family": seed["family"],
               "scope": "multi_relation" if relation_count > 1 else "single_relation",
               "function_ids": fids, "test_ids": sorted(relevant_tests), "relations": seed["relations"],
               "shared_context": {}, "reason": seed["question"],
               "contrast": "根据需求确定补测目标。候选可以被修改或否定；结果已被断言不能排除其他联合条件。",
               "evidence": {"source_operations": seed["operations"], "declaration": seed["declaration"]},
               "behavior": {"conditions": dimensions, "operations": operations, "observations": observations,
                            "relation_count": relation_count, "condition_dimensions": len(dimensions), "combinations": cells,
                            "default_transfer": seed["transfer"]},
               "test_scope": scope, "priority": seed["priority"],
               "status": "potential_gap_requires_contract_review" if cells["missing"] else "test_scope_requires_review"}
        if seed["declaration"]:
            row["resource_paths"] = [seed["declaration"]["path"]]
        candidates.append(row)
    return {"candidates": candidates, "generated_regions": len(unique), "retained_regions": len(candidates),
            "selection_ranking": ranking,
            "truncated": len(unique) > max_candidates, "max_order": max_order,
            "meaning": "Missing joint source checks guide review. Unknown scope and budget omissions are not no-gap decisions."}


def attach_legacy_scope(program, graph, candidate):
    """Keep earlier structural operators as seeds under the same input format."""
    fids = set(candidate["function_ids"])
    operations = [n for n in graph["nodes"].values() if n["function_id"] in fids]
    dimensions = []
    if candidate["family"] == "guard_activation":
        guard = candidate["evidence"]["guard"]
        for node in operations:
            if node["kind"] == "condition" and node["span"]["start_byte"] == guard["span"]["start_byte"]:
                dimensions.extend(_dimension("predicate", a["expression"], {**node, "span": a["span"]}, [False, True]) for a in node["atoms"])
    scope = test_scope(program, graph, fids, dimensions)
    candidate["test_scope"] = scope
    candidate["test_ids"] = sorted(set(candidate["test_ids"]) | set(scope["test_ids"]))
    candidate["behavior"] = {"conditions": dimensions, "operations": operations[:45],
                             "operations_truncated": len(operations) > 45,
                             "observations": [n for n in operations if n["kind"] == "observation"][:12],
                             "relation_count": len(candidate["relations"]), "condition_dimensions": len(dimensions),
                             "combinations": _combinations(dimensions, scope)}
    candidate["priority"] = 5
    return candidate
