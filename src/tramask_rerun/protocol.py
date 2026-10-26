"""Prospective protocol construction for the new evidence-based pilot run."""
from pathlib import Path

from tramask_pilot.corpus import receipt, read
from .study import PREPARATION, ROOT, RUN, now, write_new


def specification():
    return {
        "version": "tramask-evidence.v1", "created_at": now(),
        "requirements": receipt(PREPARATION / "user_requirements.txt"),
        "requirements_audit": receipt(PREPARATION / "requirements_audit.json"),
        "budget_authorization": receipt(RUN / "budget_authorization.json"),
        "provider": {"model": "deepseek-v4-flash", "temperature": 0,
                     "thinking": "disabled", "new_run_total_input_plus_output_tokens": 10_000_000,
                     "physical_repeats": 2, "random_seeds": None,
                     "repeat_interpretation": "Separate physical requests at temperature 0, not seeded or statistically independent model samples.",
                     "max_output_tokens_per_request": 8192, "large_test_views": "Python AST and TypeScript complete test definitions plus support context; explicit excerpts and gaps, exact full source retained for applying edits",
                     "parser_dependencies": {"tree-sitter": "0.25.2", "tree-sitter-typescript": "0.23.2"}, "max_input_prompt_utf8_bytes": 64000, "large_essential_material_tier_utf8_bytes": 262144, "large_tier_policy": "Common per-pair allowance based only on complete essential test size or parser inability; preserve original whole files, same source/history quotas, actual token costs reported",
                     "reservation": "UTF8 serialized request bytes + wrapper allowance + output cap; unavailable usage charged at reservation.",
                     "retry": "No automatic retry or successful-output-dependent replacement."},
        "sampling": {
            "previously_explored": {"failed": 30, "successful": 10, "cases": "previously_explored_cases.json"},
            "reserved": {"failed": 15, "successful": 5, "seed": "tramask-evidence-20261023-reserved-v1",
                         "unit": "one trial per distinct issue; disjoint from previously explored issues",
                         "eligible_pool": "metadata audit candidates excluding all prior TraMask exposure and registered other-method pilot issues",
                         "order": "SHA256(seed + ':' + task), then SHA256(seed + ':' + trial); select failed issues first, then successful excluding selected issues",
                         "replacements": False,
                         "timing": "Freeze protocol and all generation prompts before reading reserved trajectories/source/tests.",
                         "disclosure": "Reserved from method/prompt development, not globally unseen: failed corpus previously had a manual survey."},
            "calibration": "Previously designated three calibration tasks remain excluded; no held-out prompt tuning.",
            "denominators": "All 60 selected trials retained, including acquisition/replay/no-test/invalid-Q failures; pair-level and trial-level reports separated."},
        "baseline": {
            "P": "Exactly verified submitted HEAD, index and tracked working tree; clone frozen terminal filesystem with /tmp, dependencies and generated artifacts.",
            "checkpoint_source": "state_directory and validation_v03 for original 40; complete chronological replay plus independent submitted-patch validation for reserved 20.",
            "state_acceptance": "Submission state identity; stdout equality is not the replay acceptance criterion.",
            "test_selection": "Original 40 retain prior issue-relevance selection; reserved use latest actually executed focused agent-authored validation test, chosen without weakness labels.",
            "validation_inventory": "Independently enumerate all actually invoked authored validation files/scripts/inline tests from raw actions and terminal inventory, with collection/command review. Track B receives the complete qualified inventory, not the P1-selected single test. Oversize file views use complete authored test definitions with explicit ranges and omission receipts.",
            "test_version": "Use terminal file bytes where present. An absent original test may be recovered only as a separately receipted exact historical test capsule, independently verified against raw actions, materialized AFTER terminal-state proof. Never transplant historical production source or overwrite extant final tests.",
            "test_capsule_reporting": "Report native-terminal tests and recovered historical-test capsules separately, with same immutable P checkpoint and explicit file changes.",
            "stability": "Three clean baseline executions; compare collected tests/assertion outcomes and measured semantic values, not whole stdout.",
            "process_state": "Checkpoint is filesystem-only. Any necessary service setup is explicit, equal across P/Q, traced to the original test context; unavailable service state remains unresolved.",
            "timeout_source": "task.toml:[verifier].timeout_sec for tests; environment.build_timeout_sec for builds; recorded inner timeout commands preserved.",
            "historical_replay_semantics": "mini-swe-agent 2.4.5 /bin/sh, 30-second original tool timer, only timed-out action process group killed; original literal commands retained."},
        "counterfactual": {
            "preference": ["historical_target_edit", "target_local_patch_reversion", "targeted_mutation"],
            "priority_is_not_correctness": True,
            "qualification": ["build validity", "task-target relevance", "one mechanism/change isolation", "stable execution", "no syntax/import/environment failure substituted for target effect"],
            "measurement": "Original and observationally instrumented P/Q, each in three clean clones (12 runs) to qualify stable execution/effects. Probe preserves original statements, target stimuli, assertion semantics and evaluation count.",
            "alignment": "Same semantic anchor and test/input/call identity; no global event-arrival-order zip, no equality from absent markers, no normalization of meaningful values.",
            "generated_runtime": "When source changes require generation/compilation, execute the declared identical build procedure in P and Q and never test stale artifacts."},
        "pilot1": {
            "checks": {
                "E1": "Verified original P/test context and stable replay",
                "E2": "Runtime evidence target actually reached in both P/Q",
                "E3": "Executable relevant isolated Q, independently reviewed",
                "E4": "Aligned target-local effect differs",
                "E5": "Raw value at original test observation is equal",
                "E6": "Original scoped test reports no target error for either version; PASS/PASS alone is insufficient",
                "E7": "Legal setup/fixture edit preserves target operation, target input and requirement semantics",
                "E8": "Same original observation becomes different under paired modified context",
                "E9": "Independent issue/contract/verifier evidence qualifies oracle and its direction"},
            "labels": {"candidate": "E1-E6 all pass", "confirmed_masking": "E1-E8 all pass", "validated_repair": "E1-E9 all pass"},
            "classification": "Code derives labels from evidenced checks; reviewer never votes masking yes/no.",
            "other_classes": ["target_bypass", "target_not_activated", "observation_gap", "weak_oracle", "valid_discrimination", "invalid_counterfactual", "incomplete_evidence"],
            "finite_search": "No witness after finite search leaves E7/E8 unresolved, never proof of nonmasking.",
            "scope": "A local test/input witness is distinguished from full-command equivalence and discrimination by other original tests.",
            "gold_witness_creation": "Independent Codex witness-construction branch sees raw evidence and fixed P/Q only, never TraMask candidates. At most five context factors, one then at most two, all failed attempts retained. Gold context edits kept out of every generator packet.",
            "review": {"reviewers": 2, "launch": "fresh Codex threads fork_turns=none; both review every assigned pair",
                       "semantic_items": ["counterfactual_relevance", "context_legality", "oracle_validity"],
                       "required_support": "Code diff, issue clauses, legal-use explanation, and precise contract/oracle references; probe adequacy explicitly recorded.",
                       "blindness": "Allowed packet only; no prior labels, another reviewer, TraMask-generated candidates/results, method identity or hidden oracle in generation. Shared filesystem is instruction-enforced, not ACL isolation.",
                       "disagreement": "Third fresh Codex adjudicator uses concrete logs and contract, with all initial judgments immutable.",
                       "agreement": "Initial agreement and Cohen kappa per semantic item, confusion/disagreement categories, unresolved count; degenerate kappa reported undefined.",
                       "cost": "Thread launch/completion wall time, per-pair review timestamps and separate subject-run counts; wall time is not human labor time."},
            "metrics": ["replay_success_rate", "candidate_masking_pair_rate", "confirmed_masking_pair_rate", "masking_trial_rate", "unresolved_rate", "manual_verification_cost"],
            "strata": ["failed", "successful", "previously_explored", "reserved", "native_terminal_test", "historical_test_capsule"],
            "intervals": "Numerator/denominator and Wilson 95% CI for proportions; confirmed positives are conservative lower bounds.",
            "exploratory_thresholds": {"replay": "at least approximately 80% or explicit repairable environmental barriers", "existence": "at least 4 high-confidence E1-E8 witnesses from at least 3 issues, including non-calibration", "reliability": "complete E1-E8 records for positives and reported semantic agreement"}},
        "pilot2": {
            "population": "Every E1-E6 candidate; separately report independently established gold witnesses. Fixed (issue,P,Q,test,target,c0).",
            "conditions": {"C1": "issue,test,patch", "C2": "C1 + local source/call context", "C3": "C2 + relevant raw trajectory actions", "C4": "Same C3 event content/count with deterministic chronology removal/shuffle and no ordinal IDs"},
            "common_information": "Fixed target/Q descriptors and original test for all conditions; no gold context answer.",
            "candidates": 5, "independent_physical_requests_per_condition": 2,
            "output": ["factor", "location", "current_state", "proposed_state", "exact edit", "rank", "specific source/trajectory evidence"],
            "success": "Executed legal context-only E7-E8, not terminology/text overlap with gold.",
            "trajectory_window": "Post-hoc QA: recorded public actions through submission only; no online claim or future evaluation output.",
            "metrics": ["Recall@1", "Recall@3", "Recall@5", "MRR", "Executions-to-Unmask", "valid_candidate_precision", "trajectory_evidence_utilization"],
            "provenance_categories": ["historical_fixture_change", "pass_fail_execution_contrast", "object_lifecycle_change", "historical_implementation_change", "local_code_only"],
            "exploratory_threshold": "C3 minus C2 Recall@3 >=15 percentage points OR paired execution cost reduction >=25%; report per-case outcomes and uncertainty."},
        "pilot3": {
            "source": "C3 of Pilot2, both predeclared repeats reported separately and together; no best-arm selection.",
            "candidate_factors": 5, "preferred_factor_count": 1, "maximum_factor_count": 2,
            "allowed": ["fixture parameters not changing target stimulus", "resource binding", "state initialization", "legal object lifecycle", "legal setup ordering"],
            "forbidden_core": ["production implementation edit", "target stimulus change", "assertion replacement", "new observation used in place of the original observation"],
            "combined_repairs": "Retain and report separately; never count as strict context-only R2.",
            "search": "Apply independently to frozen baseline; all five ranks including failed edits/abstentions retained. Preserve exact input values/semantic invariants, not merely call text.",
            "confirmation": "Every initially successful candidate has three additional clean P/Q repetitions with originals and probes; unstable results not counted as success.",
            "minimization": "Delete each added setup operation and rerun; iterate within at most eight declared atomic operations, preserve evidence and establish 1-minimality, not global minimality; reconfirm final edit.",
            "levels": {"R1": "P/Q test edit executes", "R2": "legal context-only edit restores original observability", "R3": "independently oracle-qualified R2", "R4": "independently confirmed final P defect satisfying current issue"},
            "denominators": ["all E1-E6 candidates", "independent gold E1-E8 witnesses"],
            "metrics": ["context_unmasking_rate", "oracle_qualified_repair_rate", "independent_issue_missed_defects", "one_factor_success_rate", "median_semantic_edit_count", "median_paired_executions", "false_rejection_rate_among_independently_correct_patches"],
            "exploratory_threshold": "One semantic factor solves approximately half of independently verified repairable cases, interpreted with candidate-level success and total cost."},
        "pilot4": {
            "methods": {"M1": {"trajectory": False, "two_flip": False, "name": "direct_augmentation"},
                        "M2": {"trajectory": True, "two_flip": False, "name": "trajectory_augmentation"},
                        "M3": {"trajectory": False, "two_flip": True, "name": "code_only_two_flip"},
                        "M4": {"trajectory": True, "two_flip": True, "name": "full_tramask"}},
            "track_a": {"population": "all E1-E6 candidates", "input": "same target/test and same Q", "shared_arms": "M3 is C2 and M4 is C3; reuse exactly the registered physical requests as shared arms, never count as independent replicates.", "metrics": ["Recall@K", "first_valid_rank", "unmasking_rate", "paired_execution_count"]},
            "track_b": {"population": "all 20 reserved trials, failures and missing outputs retained", "input": "raw issue,patch,original validation tests and local source; trajectory only M2/M4; no fixed target,Q,gold masker provided", "pipeline": "At most two model calls per method/repeat. Each of two physical repeats begins with an independent stage1 request; stage1 abstention/invalid output stops that repeat, stays in the denominator, and unused allowance cannot fund extra search. Stage1 independently chooses a target/test. M1/M2 require only planned_target and are never blocked by missing Q; M3/M4 propose and execute local Q/probes. Stage2 M1/M2 sees target only, M3/M4 sees executable P/Q evidence. Any comparator needed for direct-method evaluation is constructed independently after outputs freeze and remains withheld from direct generation; its evaluation cost is separate.", "metrics": ["oracle_qualified_repair_rate", "independent_issue_missed_defects", "false_rejection_rate", "cost_per_valid_gap"]},
            "external_mutation_baseline": "Optional in requirements; no external language-specific baseline in this first cross-language rerun.",
            "fairness": "Same model/config, the same allowance of at most two requests per end-to-end method/repeat, five candidate slots, same prompt byte ceiling, same immutable P image/dependencies, same per-phase execution ceilings; input tokens and actual executions itemized.",
            "execution_budget_per_method_repeat": {"target_qualification_runs": 12, "five_candidate_four_variant_runs": 20, "success_three_repeat_runs": 60, "minimization_eight_operations_worst_36_deletion_attempts_runs": 720, "final_three_repeat_runs": 60, "total_subject_test_run_cap": 872},
            "budgets_note": "Ceilings identical across methods, spent only when phase eligible. Builds, source exports, baseline dataset construction and gold construction separately charged/reported. No extra candidate search using unused confirmation allowance.",
            "statistics": "Paired issue outcomes/discordances; exact McNemar where interpretable; paired cost differences with issue-cluster bootstrap CI. One trial per issue initially; no pseudo-independent trials. Small samples emphasize case-level results."},
        "leakage_controls": ["Raw source inputs only; no failure_analysis summaries in model packets", "No old scientific labels imported", "No gold edits in generation/ranking", "No hidden verifier/reference solution in generation", "No cross-condition outputs", "C4 event content matches C3 and chronology metadata stripped", "Independent initial semantic reviews completed before automatic TraMask candidate results are exposed", "Any post-output adjudication uses blinded neutral evidence, preserves original reviews, and is reported as post-freeze evaluation"],
        "deliverables": ["immutable protocol/prompt/code snapshots", "raw requests/responses and budget ledger", "case/input/checkpoint receipts", "all E1-E9 evidence and derived labels", "two independent reviews and any third adjudication", "all failed edits and executions", "three-repeat stability and minimization records", "P1-P4 metrics with denominators and uncertainty", "per-case HTML report", "reusable replay and experiment code plus usage instructions", "requirement-by-requirement completion audit"],
        "interpretation": "Executing and reporting all pilots is distinct from meeting exploratory scientific success thresholds. Never alter definitions or select cases to force positive results."
    }


def freeze():
    """Freeze only after prompt implementation exists; before reserved content access."""
    path = RUN / "protocol.json"
    if path.exists():
        return read(path)
    files = [Path(__file__), Path(__file__).with_name("prompts.py"),
             Path(__file__).with_name("study.py"), Path(__file__).with_name("runtime.py"),
             Path(__file__).with_name("evidence.py"), Path(__file__).with_name("metrics.py"),
             Path(__file__).with_name("sampling.py"), Path(__file__).with_name("replay.py"),
             Path(__file__).with_name("workflow.py"), Path(__file__).with_name("generation.py"),
             Path(__file__).with_name("validation_inventory.py"), Path(__file__).with_name("variants.py"),
             Path(__file__).with_name("capsules.py"), Path(__file__).with_name("reserved.py"),
             ROOT / "src/tramask_pilot/hypotheses.py", ROOT / "src/tramask_pilot/provider.py",
             ROOT / "src/tramask_pilot/submission_replay.py", ROOT / "src/tramask_pilot/submission_state.py",
             ROOT / "src/tramask_pilot/runtime.py", ROOT / "scripts/run_tramask_evidence.py"]
    protocol = specification()
    protocol["implementation_receipts"] = [receipt(p) for p in files]
    protocol["freeze_status"] = "frozen_before_reserved_content_access_and_new_model_outputs"
    write_new(path, protocol)
    for source in files:
        target = RUN / "frozen_code" / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(source.read_bytes())
    return protocol
