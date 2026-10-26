"""Search for missing distinctions, then expand through shared information.

The small set of operators describes program structure, not benchmark-specific
mutation recipes. A screened-out candidate has structural evidence only; it is
never called a proof of adequate validation.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import json
import re

from .program import evaluate_condition, reachable, stable_id


def _test_ids(program, functions):
    return sorted({c["test_id"] for c in program["calls"] if set(functions) & reachable(program, c["targets"])})


def _candidate(program, family, functions, relations, reason, contrast, evidence, *, context=None):
    functions = sorted(set(functions))
    return {"id": "candidate_" + stable_id(family, functions, context, evidence),
            "family": family, "scope": "multi_relation" if len(relations) > 1 else "single_relation",
            "function_ids": functions, "relations": relations, "shared_context": context or {},
            "test_ids": _test_ids(program, functions), "reason": reason, "contrast": contrast,
            "evidence": evidence, "status": "potential_gap_requires_contract_review"}


def _values(call, function_id):
    result = {}
    for binding in call.get("argument_bindings", []):
        if binding["function_id"] != function_id:
            continue
        value = call["literal_arguments"][binding["slot"]]
        if value["known"]:
            result[binding["parameter"]] = value["value"]
    return result


def _actual_identity(call, parameter, function_id):
    for binding in call.get("argument_bindings", []):
        if binding["function_id"] != function_id or binding["parameter"] != parameter:
            continue
        slot = binding["slot"]
        literal = call["literal_arguments"][slot]
        value = call["arguments"][slot].get("binding") or {}
        identity = value.get("origin_binding_id") or value.get("binding_id")
        if literal["known"] and isinstance(literal["value"], (dict, list, tuple)):
            return ("binding", identity) if identity else None
        if literal["known"]:
            return ("literal", json.dumps(literal["value"], sort_keys=True))
        if identity:
            return ("binding", identity)
    return None


def _compatible(program, a, af, ae, b, bf, be):
    if a["test_id"] != b["test_id"] or a.get("contexts") or b.get("contexts"):
        return False
    if program["functions"][af].get("owner") or program["functions"][bf].get("owner"):
        ai = (a.get("receiver_binding") or {}).get("origin_binding_id")
        bi = (b.get("receiver_binding") or {}).get("origin_binding_id")
        if not ai or ai != bi:
            return False
    if ae.get("parameter") or be.get("parameter"):
        ai = _actual_identity(a, ae.get("parameter"), af)
        bi = _actual_identity(b, be.get("parameter"), bf)
        # Equal literal containers are values, not evidence of the same object.
        if not ai or ai != bi or ai[0] != "binding":
            return False
    ak, bk = ae.get("key"), be.get("key")
    if ak and bk:
        av, bv = _actual_identity(a, ak, af), _actual_identity(b, bk, bf)
        # Literal indices embedded directly in the implementation also compare.
        if av is None or bv is None:
            return False
        if av != bv:
            return False
    return True


def _state_witnesses(program, af, ae, bf, be):
    result = []
    for a in program["calls"]:
        if af not in a["targets"]:
            continue
        for b in program["calls"]:
            if bf not in b["targets"] or a["span"]["end_byte"] > b["span"]["start_byte"]:
                continue
            if _compatible(program, a, af, ae, b, bf, be) and b["direct_observation"]["observation_ids"]:
                result.append({"test_id": a["test_id"], "calls": [a["id"], b["id"]],
                               "observations": b["direct_observation"]["observation_ids"]})
    return result


def _guard_candidates(program):
    candidates, checked = [], []
    for guard in program["frontend"]["guards"]:
        fid = guard["function_id"]
        if fid not in program["changed"]:
            continue
        calls = [c for c in program["calls"] if fid in c["targets"]]
        if not calls:
            continue
        params = {p["name"] for p in program["functions"][fid]["parameters"]}
        used = params & set(guard["condition"]["free_identifiers"])
        controlled = [e for e in program["edges"] if e["from"] == fid and
                      guard["span"]["start_byte"] <= e["span"]["start_byte"] < guard["span"]["end_byte"]]
        # One scalar boundary alone is outside the combination-gap abstraction.
        if len(used) < 2 and not controlled:
            continue
        outcomes = [{"call_id": c["id"], "test_id": c["test_id"],
                     **evaluate_condition(guard["condition"]["text"], _values(c, fid))} for c in calls]
        known = {o["value"] for o in outcomes if o["known"]}
        relations = [{"from": fid, "to": controlled[0]["to"] if controlled else fid,
                      "kind": "guard_influence", "condition": guard["condition"]["text"]}]
        row = _candidate(program, "guard_activation", [fid] + [e["to"] for e in controlled], relations,
            "原测试的可静态求值输入没有区分该组合条件的两个结果。",
            "保持合法的共同前提，构造条件两侧的输入，并观察受条件控制的结果或副作用。",
            {"guard": guard["condition"], "outcomes": outcomes, "missing_outcomes": sorted({False, True} - known)})
        if known == {False, True}:
            row["status"] = "both_guard_outcomes_in_source_not_adequacy_proof"
            checked.append(row)
        elif known:
            candidates.append(row)
    return candidates, checked


def _observation_candidates(program):
    result = []
    by_function = defaultdict(list)
    for call in program["calls"]:
        for target in set(call["targets"]) & program["changed"]:
            by_function[target].append(call)
    for fid, calls in sorted(by_function.items()):
        summary = program["summaries"].get(fid, {})
        if not summary.get("returns_value"):
            continue
        return_fields = set(summary.get("return_fields", []))
        observed = set().union(*(set(c["direct_observation"]["fields"]) for c in calls))
        observed.update(set().union(*(set(c["direct_observation"]["whole_fields"]) for c in calls)))
        missing = return_fields - observed
        unobserved = [c for c in calls if not c["direct_observation"]["observation_ids"]]
        if missing or (unobserved and not any(c["direct_observation"]["observation_ids"] for c in calls)):
            result.append(_candidate(program, "result_observation", [fid],
                [{"from": fid, "to": "test_observation", "kind": "result_flow"}],
                "原测试没有直接检查调用结果，或只检查了返回对象的部分字段。副作用检查仍需结合原测试判断。",
                "保留原操作，补充与任务相关的结果字段或后续观察；不要把无返回值操作自动当成缺口。",
                {"unobserved_call_ids": [c["id"] for c in unobserved], "return_fields": sorted(return_fields),
                 "observed_fields": sorted(observed), "missing_fields": sorted(missing)}))
    return result


def _state_candidates(program):
    resources = defaultdict(dict)
    # Share formal-state regions only when some call site passes the same bound
    # object. A parameter spelling by itself never joins two functions.
    formal_groups = defaultdict(set)
    for call in program["calls"]:
        for binding in call.get("argument_bindings", []):
            target, parameter = binding["function_id"], binding["parameter"]
            actual = _actual_identity(call, parameter, target)
            if actual and actual[0] == "binding":
                formal_groups[(call["test_id"], actual)].add((target, parameter))
    for call in program["frontend"]["production_calls"]:
        for binding in call["argument_bindings"]:
            argument = call["arguments"][binding["slot"]]
            if argument["kind"] != "identifier" or call.get("contexts"):
                continue
            fid = binding["function_id"]
            if not any(t["function_id"] == fid and t.get("resolved") for t in call["targets"]):
                continue
            source = program["sources"][call["span"]["path"]]
            start = program["functions"][call["function_id"]]["body_span"]["start_byte"]
            prefix = source.data[start:call["span"]["start_byte"]].decode()
            assignments = list(re.finditer(r"\b" + re.escape(argument["text"]) + r"\s*=(?!=)", prefix))
            version = assignments[-1].start() if assignments else -1
            formal_groups[(call["function_id"], argument["text"], version)].add((fid, binding["parameter"]))
    representatives = {}
    def find(item):
        representatives.setdefault(item, item)
        if representatives[item] != item:
            representatives[item] = find(representatives[item])
        return representatives[item]
    for group in formal_groups.values():
        if group:
            root = min(group)
            for item in sorted(group):
                representatives[find(item)] = find(root)
    for fid, summary in program["summaries"].items():
        if program["functions"][fid]["name"] in {"__init__", "constructor"}:
            continue
        for effect in summary["effects"]:
            resource = effect["resource"]
            if effect.get("parameter"):
                root = find((fid, effect["parameter"]))
                suffix = effect["access"].split(".", 1)[1:]
                resource = "shared_parameter::" + stable_id(root, suffix)
            resources[resource].setdefault((fid, effect["mode"]), effect)
    candidates, checked = [], []
    for resource, entries in sorted(resources.items()):
        writers = [(f, e) for (f, mode), e in entries.items() if mode in {"write", "remove"}]
        readers = [(f, e) for (f, mode), e in entries.items() if mode == "read"]
        for af, ae in writers:
            for bf, be in readers:
                if af == bf or not {af, bf} & program["changed"]:
                    continue
                witnesses = _state_witnesses(program, af, ae, bf, be)
                row = _candidate(program, "state_handoff", [af, bf],
                    [{"from": af, "to": bf, "kind": "shared_state", "resource": resource}],
                    "未找到先修改、后观察同一对象及相关键的直接测试证据。",
                    "连接真实的状态修改与读取，保持对象和键绑定，并检查修改对读取结果的影响。",
                    {"write": ae, "read": be, "joint_witnesses": witnesses}, context={"resource": resource})
                if witnesses:
                    row["status"] = "joint_binding_and_observation_in_source_not_adequacy_proof"
                    checked.append(row)
                else:
                    candidates.append(row)
        # Expansion follows a concrete shared resource. It does not wait for a single-edge failure.
        for (af, ae), (bf, be) in combinations(writers, 2):
            if af == bf:
                continue
            for cf, ce in readers:
                if cf in {af, bf} or not {af, bf, cf} & program["changed"]:
                    continue
                witnesses = defaultdict(list)
                for a in program["calls"]:
                    if af not in a["targets"]:
                        continue
                    for b in program["calls"]:
                        if bf not in b["targets"] or not _compatible(program, a, af, ae, b, bf, be):
                            continue
                        for c in program["calls"]:
                            if cf not in c["targets"] or not _compatible(program, b, bf, be, c, cf, ce):
                                continue
                            if max(a["span"]["end_byte"], b["span"]["end_byte"]) > c["span"]["start_byte"] or not c["direct_observation"]["observation_ids"]:
                                continue
                            order = "first_then_second" if a["span"]["start_byte"] < b["span"]["start_byte"] else "second_then_first"
                            witnesses[order].append(c["test_id"])
                row = _candidate(program, "state_composition", [af, bf, cf],
                    [{"from": af, "to": cf, "kind": "shared_state", "resource": resource},
                     {"from": bf, "to": cf, "kind": "shared_state", "resource": resource}],
                    "多个操作影响同一状态，但原测试未提供两种相关操作顺序的共同观察。",
                    "保持对象和相关键相同，比较两种操作顺序，再执行同一读取。若涉及异步操作，保留未完成操作并追加完成事件。由需求判断结果应相同还是不同。",
                    {"effects": [ae, be, ce], "order_witnesses": dict(witnesses)},
                    context={"resource": resource, "expansion_reason": "two_modifiers_share_the_observed_state"})
                if len(witnesses) == 2:
                    row["status"] = "both_orders_in_source_not_adequacy_proof"
                    checked.append(row)
                else:
                    candidates.append(row)
    return candidates, checked


def _projection_candidates(program):
    # Match actual arguments inside the SAME caller. Equal formal names alone do not connect functions.
    uses = defaultdict(list)
    for call in program["frontend"]["production_calls"]:
        for binding in call["argument_bindings"]:
            fid = binding["function_id"]
            if not any(t["function_id"] == fid and t.get("resolved") for t in call["targets"]):
                continue
            fields = program["summaries"].get(fid, {}).get("parameter_fields", {}).get(binding["parameter"], [])
            if not fields:
                continue
            arg = call["arguments"][binding["slot"]]
            if arg["kind"] != "identifier":
                continue
            uses[(call["function_id"], arg["text"])].append((fid, set(fields), call, binding))
    result = []
    for (caller, actual), group in sorted(uses.items()):
        for a, b in combinations(group, 2):
            af, aset, ac, _ = a
            bf, bset, bc, _ = b
            if af == bf or not {caller, af, bf} & program["changed"]:
                continue
            if bset < aset:
                af, aset, ac, bf, bset, bc = bf, bset, bc, af, aset, ac
            if not aset < bset:
                continue
            # Rebinding between the two reads invalidates a shared-value claim.
            source = program["sources"][ac["span"]["path"]]
            first, last = sorted([ac["span"]["start_byte"], bc["span"]["start_byte"]])
            between = source.data[first:last].decode()
            if re.search(r"\b" + re.escape(actual) + r"\s*=(?!=)", between):
                continue
            result.append(_candidate(program, "projection_difference", [caller, af, bf],
                [{"from": caller, "to": af, "kind": "argument_projection", "fields": sorted(aset)},
                 {"from": caller, "to": bf, "kind": "argument_projection", "fields": sorted(bset)}],
                "同一调用方传递的值在两个处理过程中保留了不同的字段。需要检查较少字段是否足以表示后续语义。",
                "构造保留字段相同、额外字段不同的两个输入。在同一共享上下文中使用它们，检查后续行为是否保持需求规定的区别。",
                {"calls": [ac["span"], bc["span"]], "retained_fields": sorted(aset), "additional_fields": sorted(bset - aset)},
                context={"caller": caller, "actual": actual, "binding_status": "same_unreassigned_local_spelling",
                         "expansion_reason": "shared_value_has_different_field_projections"}))
    return result


def _flow_candidates(program):
    candidates, checked = [], []
    flows = [e for e in program["edges"] if e["kind"] == "value_flow"]
    bindings = {b["id"]: b for b in program["frontend"]["bindings"]}
    for edge in flows:
        af, bf, caller = edge["from"], edge["to"], edge["caller"]
        if not {af, bf, caller} & program["changed"]:
            continue
        witnesses = []
        for call in program["calls"]:
            if not call["direct_observation"]["observation_ids"]:
                continue
            if caller in call["targets"] and not call.get("contexts"):
                witnesses.append({"test_id": call["test_id"], "call_id": call["id"], "kind": "observed_wrapper"})
            if bf not in call["targets"]:
                continue
            for argument in call["arguments"]:
                loc = argument["span"]
                binding = bindings.get((argument.get("binding") or {}).get("binding_id"))
                if binding:
                    loc = binding["value"]["span"]
                producers = [p for p in program["calls"] if p["test_id"] == call["test_id"] and af in p["targets"]
                             and p["span"]["start_byte"] == loc["start_byte"] and p["span"]["end_byte"] == loc["end_byte"]]
                if producers:
                    witnesses.append({"test_id": call["test_id"], "call_id": call["id"], "kind": "direct_result_argument"})
        row = _candidate(program, "value_handoff", [af, bf, caller], [edge],
            "实现存在真实结果到下游参数的数据联系，但原测试没有直接检查该交接过程。",
            "用生产者的真实结果调用消费者。保留共同输入约束，检查下游结果，避免由手工替身绕过交接。",
            {"joint_witnesses": witnesses})
        if witnesses:
            row["status"] = "value_handoff_in_source_not_adequacy_proof"
            checked.append(row)
        else:
            candidates.append(row)
    # Only compose actual data handoffs. Plain chains of helper calls are not
    # automatically counted as new semantic dimensions.
    for first in flows:
        for second in flows:
            if first["to"] != second["from"] or first["caller"] != second["caller"] or first["from"] == second["to"]:
                continue
            if first["span"] != second["producer_span"]:
                continue  # Two invocations of the same function need not share a value.
            middle = program["summaries"].get(first["to"], {})
            semantic_middle = middle.get("parameter_fields") or middle.get("effects") or any(g["function_id"] == first["to"] for g in program["frontend"]["guards"])
            if not semantic_middle or not {first["from"], first["to"], second["to"], first["caller"]} & program["changed"]:
                continue
            candidates.append(_candidate(program, "value_composition", [first["from"], first["to"], second["to"], first["caller"]],
                [first, second], "两段数据交接经过会读取结构、修改状态或分支的中间处理；局部测试可能没有验证组合后的含义。",
                "保留中间处理及其输入结构，构造中间转换能够影响末端结果的输入，并检查最终观察。",
                {"middle_summary": middle}, context={"expansion_reason": "connected_value_flows_cross_a_semantic_transform"}))
    return candidates, checked


def search(program):
    guards, guard_checked = _guard_candidates(program)
    states, state_checked = _state_candidates(program)
    flows, flow_checked = _flow_candidates(program)
    candidates = guards + _observation_candidates(program) + states + _projection_candidates(program) + flows
    unique = {c["id"]: c for c in candidates}
    return {"candidates": sorted(unique.values(), key=lambda c: (c["family"], c["id"])),
            "screened": guard_checked + state_checked + flow_checked,
            "screening_meaning": "Static witnesses remove the corresponding structural-gap hypothesis. Semantic adequacy and execution on this patch still require review."}
