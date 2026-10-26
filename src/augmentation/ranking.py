"""Rank source-supported distinctions, without reference patches or labels."""
from __future__ import annotations

import math
import re
from collections import Counter


def words(text):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9]+", text)
            if len(w) > 2} - {"the", "and", "for", "with", "this", "return", "true", "false", "none", "self", "test", "not"}


def focus(candidate):
    operations = candidate.get("behavior", {}).get("operations", [])
    ids = set(candidate.get("evidence", {}).get("source_operations", []))
    return [n for n in operations if n["id"] in ids] or [n for n in operations if n.get("changed")][:12] or operations[:12]


def signature(candidate):
    dims = candidate.get("behavior", {}).get("conditions", [])
    # Distinct conditions in one function remain distinct search targets.
    conditions = {"condition:" + d["id"] for d in dims}
    operations = {"operation:" + n["id"] for n in focus(candidate)}
    return conditions | operations or {"candidate:" + candidate["id"]}


def rank_candidates(candidates, issue="", *, limit=None):
    """Greedy evidence diversity, with every score component retained for review.

    Missing and unknown checks both deserve review. Unknown is never scored as
    a proven gap. Family names and hashed IDs are not relevance features.
    """
    descriptions = []
    for c in candidates:
        ops = focus(c)
        dims = c.get("behavior", {}).get("conditions", [])
        descriptions.append(words(" ".join(n.get("code", "") for n in ops)
                                  + " " + " ".join(d["expression"] for d in dims)))
    frequency = Counter(w for ws in descriptions for w in ws)
    issue_words = words(issue)
    pool = []
    for index, (candidate, tokens) in enumerate(zip(candidates, descriptions)):
        ops = focus(candidate)
        dims = candidate.get("behavior", {}).get("conditions", [])
        matched = sorted(tokens & issue_words)
        relevance = sum(1 + math.log((len(candidates) + 1) / (frequency[w] + 1)) for w in matched)
        ids = {n["id"] for n in ops}
        relations = [e for e in candidate.get("relations", []) if e["from"] in ids and e["to"] in ids]
        transfer = candidate.get("behavior", {}).get("default_transfer") or {}
        contrasted_flow = bool(transfer.get("downstream_guards"))
        # A changed exit guarding a later operation, or a value handed to a
        # consumer, describes a possible behavioral effect more directly than
        # a large undirected neighborhood does.
        effect = any(e["kind"] in {"may_prevent_continuation", "value_flow", "default_to_consumer", "symbol_dispatch"}
                     for e in relations) or contrasted_flow
        changed_ids = {n["id"] for n in ops if n.get("changed")}
        changed_effect = any(e["from"] in changed_ids and e["kind"] in {"may_prevent_continuation", "value_flow", "symbol_dispatch"}
                             for e in relations) or contrasted_flow and bool(changed_ids)
        unchanged_ids = ids - changed_ids
        existing_interaction = any(e["from"] in changed_ids and e["to"] in unchanged_ids
                                   and e["kind"] in {"may_prevent_continuation", "value_flow", "shared_state"}
                                   for e in relations) or contrasted_flow and bool(changed_ids) and bool(unchanged_ids)
        changed = sum(bool(n.get("changed")) for n in ops)
        concrete = sum(d["kind"] in {"predicate", "presence", "value_category"} for d in dims)
        components = {"requirement_overlap": round(4 * math.log1p(relevance / math.sqrt(max(1, len(tokens)))), 4),
                      "changed_source": 3.0 if changed else 0.0,
                      "explicit_effect": 3.0 if effect else 0.0,
                      "changed_effect": 3.0 if changed_effect else 0.0,
                      "existing_behavior_interaction": 3.0 if existing_interaction else 0.0,
                      "concrete_conditions": min(concrete, 2) * 0.75,
                      "condition_focus": 2.0 / max(1, len(dims)),
                      "small_focus": 1.0 / max(1, len(ops)),
                      "joint_dimensions": 1.0 if len(dims) >= 2 else 0.0}
        score = sum(components.values())
        pool.append((candidate, score, components, matched, signature(candidate), index))
    selected, signatures, receipts = [], [], []
    while pool and (limit is None or len(selected) < limit):
        def adjusted(row):
            overlap = max((len(row[4] & s) / len(row[4] | s) for s in signatures), default=0)
            return row[1] - 8 * overlap
        best = max(pool, key=lambda row: (adjusted(row), -row[5]))
        value = adjusted(best)
        pool.remove(best)
        candidate, score, components, matched, sig, _ = best
        selected.append(candidate)
        signatures.append(sig)
        receipts.append({"candidate_id": candidate["id"], "rank": len(selected),
                         "score": round(value, 4), "components": components,
                         "repeated_evidence_penalty": round(score - value, 4),
                         "matched_requirement_words": matched})
    return selected, receipts
