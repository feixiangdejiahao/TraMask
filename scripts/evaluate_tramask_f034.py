"""Materialize manually reviewed F034 outcomes from the immutable raw evidence.

This is a case-specific adjudication, not a generic outcome classifier. The
public-contract and fixed-row decisions were reviewed before this derivation.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tramask_pilot.corpus import RUN, read, receipt, write

ROOT = RUN / "runs/F034/downstream"
MASK = "bc4b6a8554d61fbf201c4a06a15d51b568eb8738f2ce2b2c0266ecbb2baf20f4"
ADDED = "a7a34a508f8a9fd05724c0adc856daca773113cc90fd9a7ed2526a593906332e"


def scoped(events, input_id, channel):
    return [{k: e[k] for k in ("anchor", "invocation", "value")}
            for e in events if e.get("input") == input_id and e["channel"] == channel]


def main():
    groups = []
    for request in sorted(ROOT.glob("pilot*/*/repeat_*/prepared_request.json")):
        group = request.parent
        recovery = read(group / "candidate_recovery.json")
        rows = []
        for path in sorted(group.glob("candidate_*/candidate.json")):
            d = path.parent
            candidate = read(path)
            validation = read(d / "validation.json")
            manual = read(d / "manual_review.json") if (d / "manual_review.json").exists() else None
            row = {"rank": candidate["rank"], "candidate": receipt(path),
                   "raw_response_schema_valid": recovery["raw_schema_valid"],
                   "executed": False, "validated_unmasking": False, "validated_success": False,
                   "augmented_assertion_discrimination": False,
                   "new_delivered_patch_defect_confirmed": False,
                   "legally_admissible": bool(manual and manual["approved_for_execution"])}
            summary = d / "paired_execution/summary.json"
            if summary.exists():
                records = {name: read(d / "paired_execution" / name / "execution.json")
                           for name in ("p_original", "q_original", "p_instrumented", "q_instrumented")}
                assert all(not x["timed_out"] and not x.get("transport_error") for x in records.values())
                effects = {v: scoped(records[v + "_instrumented"]["events"], MASK, "effect") for v in ("p", "q")}
                observations = {v: scoped(records[v + "_instrumented"]["events"], MASK, "observation") for v in ("p", "q")}
                assert all(len(x) == 2 for x in effects.values()) and effects["p"] != effects["q"]
                assert len(observations["p"]) == 3 and observations["p"] == observations["q"]
                direct = "direct_augmentation" in d.parts
                row.update(executed=True, status="executed_general_augmentation_only" if direct else "executed_no_validated_unmasking",
                           continued_target_exercise=True, target_effect_difference=True,
                           original_observation_discrimination=False,
                           matched_original_effects=effects, matched_original_observations=observations,
                           after_context_still_masks_at_original_observation=True,
                           public_contract_oracle_valid=True, fixed_q_preserved=True,
                           full_command_newly_discriminates=False,
                           baseline_full_command_already_discriminated=True,
                           raw_strict_track_admissible=recovery["raw_schema_valid"],
                           analysis_track="raw_strict_schema" if recovery["raw_schema_valid"] else "mechanically_recovered_candidate_analysis",
                           cost={"candidate_PQ_pairs": 1, "corresponding_instrumented_PQ_pairs": 1,
                                 "subject_runs": 4, "minimization_pairs": 0, "additional_provider_calls": 0},
                           evidence=[receipt(summary)] + [receipt(d / "paired_execution" / name / "execution.json") for name in records],
                           noninterference="P original and instrumented pass; Q original and instrumented report TestDefaultArguments FAIL with the same relevant script diagnostics. Q original shell status is 0 because of tail; instrumented status is the actual runner 1. These are explicitly distinct exit semantics. Original row and new-row values are measured by unchanged common probes.",
                           correctness_direction="Public issue requires omitted fixed arguments to receive their defaults. P satisfies the reviewed new assertion; Q violates it. No new defect in delivered P or suite-level detection improvement is established.",
                           minimization={"status": "not_applicable_to_setup_unmasking", "reason": "No setup-only unmasking succeeded. Direct augmentation is reported at its original ranked edit size and is not claimed minimal."})
                if direct:
                    added = {v: scoped(records[v + "_instrumented"]["events"], ADDED, "observation") for v in ("p", "q")}
                    added_effects = {v: scoped(records[v + "_instrumented"]["events"], ADDED, "effect") for v in ("p", "q")}
                    assert added["p"] != added["q"] and all(added_effects.values())
                    assert added_effects["p"] != added_effects["q"]
                    assert "script: func f(a = 1, b = 2, rest...) { return [a, b, rest] }; f(9)" in records["q_original"]["stdout"]
                    row.update(validated_success=True, augmented_assertion_discrimination=True,
                               added_row_observations=added, added_row_effects=added_effects,
                               reasoning="Added f(9) row returns [9,2,[]] under P and [9,nil,[]] under Q. Public default-argument contract establishes the expected value independently. The original final masked row remains [] in both; no original-context unmasking is claimed.",
                               setup_edit_size=None, new_table_rows=2 if "repeat_01" in d.parts else 1)
                else:
                    row.update(true_setup_operation_count=2,
                               reasoning="A variable and its use replace literal 5 in a different existing row, preserving its oracle. The fixed final masked row is unchanged and still has equal raw public observations. Failures elsewhere already existed before the edit and do not count.")
            elif validation["status"] == "invalid_candidate":
                row.update(status="invalid_candidate", reason=validation.get("reason"))
            elif validation["status"] == "no_proposal":
                row.update(status="no_proposal", reason=candidate.get("reason"))
            elif manual and not manual["approved_for_execution"]:
                row.update(status="rejected_semantic_legality", reason=manual["reason"])
            else:
                assert "direct_augmentation" in d.parts and candidate["rank"] > 1
                row.update(status="not_executed_after_rank1_general_augmentation_success",
                           reason="Frozen stop-at-first-success applies to the direct-augmentation arm. Original candidate and legality review are retained; no execution success is inferred for this slot.")
            write(d / "evaluation.json", row)
            rows.append(row)
        groups.append({"request_id": read(request)["id"], "raw_schema_valid": recovery["raw_schema_valid"],
                       "candidate_slots": 5, "executed_candidates": sum(x["executed"] for x in rows),
                       "first_validated_unmasking_rank": None,
                       "first_general_augmentation_rank": next((x["rank"] for x in rows if x["augmented_assertion_discrimination"]), None),
                       "statuses": [x["status"] for x in rows],
                       "candidate_evaluations": [receipt(p) for p in sorted(group.glob("candidate_*/evaluation.json"))]})
    write(ROOT / "evaluation.json", {"case_id": "F034", "status": "complete",
          "groups": groups, "confirmed_mask_scope": MASK,
          "validated_setup_unmasking": False, "confirmed_new_delivered_patch_defects": 0,
          "general_augmentation_successful_repeats": 2, "general_augmentation_distinct_pairs": 1,
          "whole_command_sensitivity_improvement": False,
          "cost": {"physical_provider_calls": 14, "candidate_slots": 70,
                   "executed_candidates": 3, "candidate_PQ_pairs": 3,
                   "instrumented_PQ_pairs": 3, "subject_runs": 12, "minimization_pairs": 0},
          "evaluation_code": receipt(Path(__file__))})
    print("F034: 14 calls / 70 slots; 3 candidates executed; 0 setup unmasking; 2 direct-augmentation repeat successes on 1 task.")


if __name__ == "__main__":
    main()
