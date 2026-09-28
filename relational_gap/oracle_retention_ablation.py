"""Offline source-oracle retention ablation; no admission or subject execution.

Only program-recorded atomic neutralizations are reversed. Inputs absorbed into
those neutralizations are recovered from their original source-backed edits.
The resulting whole-observation oracle is a hypothesis, not a validity claim.
"""
from __future__ import annotations

import collections
import copy
from dataclasses import asdict, dataclass
import hashlib
import json

from anchor_retrieval.syntax import Source, walk
from .atomic_observations import _neutralization, _overlap
from .frontend import source_text


@dataclass(frozen=True)
class RetentionBudget:
    max_candidates: int = 128
    max_inputs: int = 4096

    def __post_init__(self):
        if type(self.max_candidates) is not int or not 1 <= self.max_candidates <= 128:
            raise ValueError("max_candidates must be an integer between 1 and 128")
        if type(self.max_inputs) is not int or self.max_inputs < 1:
            raise ValueError("max_inputs must be a positive integer")


def _key(edit):
    span = edit["span"]
    return (span["path"], span["start_byte"], span["end_byte"], edit["before"], edit["after"])


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]


def _source_edit(corpus, edit):
    if source_text(corpus, edit["span"]) != edit["before"]:
        raise ValueError("edit_source_bytes_mismatch")
    if not isinstance(edit["after"], str):
        raise ValueError("edit_after_not_text")


def _restore(corpus, candidate, observations, source_cache):
    if candidate.get("execution_lane") != "source_q":
        raise ValueError("not_source_q_lane")
    base = candidate.get("base_test_id")
    if base not in corpus.get("tests", {}):
        raise ValueError("missing_base_test")
    edits = candidate.get("edits", [])
    if any("expected" in e.get("role", "") or "oracle" in e.get("role", "") for e in edits):
        raise ValueError("oracle_edit_present")
    if candidate.get("oracle", {}).get("mode") == "semantic_expected_holes":
        raise ValueError("semantic_oracle_mode")
    for edit in edits:
        _source_edit(corpus, edit)
    neutral = [e for e in edits if e.get("role") == "atomic_neutralization"]
    retained = [copy.deepcopy(e) for e in edits if e.get("role") != "atomic_neutralization"]
    atomic = candidate.get("atomic_observation", {})
    original = atomic.get("input_edits")
    consumed = []
    if neutral:
        if not isinstance(original, list):
            raise ValueError("missing_original_input_edits")
        for edit in original:
            _source_edit(corpus, edit)
            if edit.get("role") == "atomic_neutralization" or "expected" in edit.get("role", ""):
                raise ValueError("nested_or_oracle_input_record")
        for recorded in neutral:
            observation = observations.get(recorded.get("observation_id"))
            if observation is None or observation.get("test_id") != base:
                raise ValueError("neutralized_observation_not_owned")
            path = recorded["span"]["path"]
            if path not in source_cache:
                meta = corpus["sources"][path]
                source = Source(path, meta["code"], meta.get("language", corpus.get("language")))
                source_cache[path] = source, {(n.start_byte, n.end_byte): n for n in walk(source.root)}
            source, nodes = source_cache[path]
            replayed, absorbed = _neutralization(source, observation, nodes, original)
            if (_key(replayed) != _key(recorded)
                    or replayed["rule"] != recorded.get("rule")):
                raise ValueError("neutralization_replay_mismatch")
            consumed.extend(absorbed)
        # Input edits may have disappeared from the top-level edit list because
        # their changed actual expression was embedded in a neutralization.
        for edit in consumed:
            if _key(edit) not in {_key(e) for e in retained}:
                retained.append(copy.deepcopy(edit))
        restored_keys = collections.Counter(_key(e) for e in retained)
        if any(restored_keys[k] < count for k, count in collections.Counter(_key(e) for e in original).items()):
            raise ValueError("original_input_or_guard_would_be_lost")
    if any(_overlap(a["span"], b["span"]) for i, a in enumerate(retained) for b in retained[i + 1:]):
        raise ValueError("restored_edits_overlap")
    out = copy.deepcopy(candidate)
    out["id"] = "wholeq_" + _digest([base, [_key(e) for e in retained]])
    out["edits"] = retained
    out["static_parent_id"] = candidate["id"]
    out["ablation_parent_id"] = candidate["id"]
    out["parent_candidate_id"] = candidate["id"]
    out.pop("semantic_model_judgment", None)
    out.pop("atomic_observation", None)
    out.pop("source_observation_id", None)
    out.pop("observation_id", None)
    ids = [o["id"] for o in observations.values() if o.get("test_id") == base]
    ids.extend(candidate.get("oracle", {}).get("assertion_ids", []))
    out["oracle"] = dict(out.get("oracle", {}), mode="retain_all",
                         assertion_ids=list(dict.fromkeys(ids)),
                         applicability="whole_source_observation_hypothesis_requires_independent_evaluation")
    out["ablation"] = {
        "mode": "restore_neutralized_source_observations",
        "original_candidate_ids": [candidate["id"]],
        "original_execution_lane": "source_q",
        "restored_observation_ids": [e["observation_id"] for e in neutral],
        "removed_neutralizations": copy.deepcopy(neutral),
        "recovered_absorbed_input_edits": copy.deepcopy(consumed),
        "original_selected_observation_id": candidate.get("source_observation_id"),
        "status": "whole_observation_hypothesis",
        "already_whole": not neutral,
        "preservation": "all_other_edits_preserved; absorbed_input_edits_replayed_from_source_record",
        "limitations": ["restored_expectations_may_be_stale", "earlier_assertions_may_stop_later_actions",
                        "existing_exception_and_normal_result_guards_remain_unchanged"],
    }
    return out


def restore_source_observations(corpus: dict, candidates: list[dict],
                                budget: RetentionBudget | None = None) -> dict:
    """Uniformly restore source-q candidates, deduplicate, and rotate per base.

    No target labels, model decisions or execution outcomes participate. Only
    source snapshots and the frozen source-q edit records are read.
    """
    budget = budget or RetentionBudget()
    observations = {o["id"]: o for o in corpus.get("capsules", [])}
    source_cache, unique, queues, unknowns = {}, {}, collections.OrderedDict(), []
    for candidate in candidates[:budget.max_inputs]:
        try:
            restored = _restore(corpus, candidate, observations, source_cache)
            # Byte-equivalence also includes support/import materialization.
            fingerprint = _digest([restored["base_test_id"], [_key(e) for e in restored["edits"]],
                                   restored.get("imports", []), restored.get("support", [])])
            if fingerprint in unique:
                previous = unique[fingerprint]
                previous["ablation"]["original_candidate_ids"].append(candidate["id"])
                continue
            restored["id"] = "wholeq_" + fingerprint
            # This is a new independently prepared source candidate. The old
            # frozen candidate remains linked through ablation_parent_id.
            restored["static_parent_id"] = restored["id"]
            unique[fingerprint] = restored
            queues.setdefault(restored["base_test_id"], collections.deque()).append(restored)
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            unknowns.append({"candidate_id": candidate.get("id"), "reason": str(exc)})
    output = []
    active = list(queues)
    while active and len(output) < budget.max_candidates:
        remaining = []
        for base in active:
            output.append(queues[base].popleft())
            if queues[base]:
                remaining.append(base)
            if len(output) == budget.max_candidates:
                break
        active = remaining
    return {"version": 1, "budget": asdict(budget), "candidates": output, "unknowns": unknowns,
            "counts": {"input_candidates": len(candidates), "inspected": min(len(candidates), budget.max_inputs),
                       "unique_pool": len(unique), "candidates": len(output), "unknown": len(unknowns),
                       "budget_exhausted": len(unique) > len(output) or len(candidates) > budget.max_inputs}}
