"""Synthetic authorizations in tmp_path only; all transports are pure stubs."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tramask_pilot import hypotheses, provider as original_provider
from tramask_rerun import continuation_dispatch_v01 as dispatch
from tramask_rerun import provider_continuation_v01 as provider
from tramask_rerun import transport_adapter, variants


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return dispatch._receipt(path)


@pytest.fixture
def queue(tmp_path):
    run = tmp_path / "synthetic_run"
    run.mkdir()
    old = {"version": 1, "limit_tokens": 10_000_000, "calls": {
        "baseline": {"status": "settled", "request_sha256": "0" * 64,
                     "reserved_tokens": 10_000_000, "charged_tokens": 9_968_405}}}
    ledger_path = run / "provider_budget.json"
    old_receipt = write(ledger_path, old)
    snapshot = write(run / "baseline_snapshot.json", old)
    selected = {"id": "selected", "command": "python /tmp/check.py",
                "files": {"tmp/check.py": "assert True\n"}}
    packet = {"selected_test": selected, "validation_tests": [selected], "final_sources": {"app/a.py": "value = 1\n"}}
    packet_receipt = write(run / "public_packet.json", packet)
    rows = []
    cells = [(c, r) for c in ["C1", "C2", "C3", "C4", "M1", "M2"] for r in [1, 2]]
    for ordinal in range(1, 50):
        category = "track_b_stage2" if ordinal <= 36 else "HS005_reference_completion" if ordinal == 37 else "HF012_context_track_a"
        request = {"id": f"synthetic/request/{ordinal}", "system": "Synthetic test only",
            "prompt": json.dumps({"material": {"selected_test": {"id": "selected"}}}),
            "max_tokens": 8192, "dispatchable": True, "status": "prepared",
            "validation_context": {"candidate_slots": 5, "original_command": selected["command"],
                                   "editable_paths": ["tmp/check.py"], "edit_policy": "general_augmentation"}}
        rp = run / f"prepared/{ordinal:03d}/prepared_request.json"
        request_receipt = write(rp, request)
        payload, fingerprint = dispatch._payload(request)
        pp = rp.parent / "provider_payload.json"
        pp.write_bytes(payload)
        row = {"queue_ordinal": ordinal, "category": category, "dispatchable": True,
               "prepared_request": request_receipt, "provider_payload": dispatch._receipt(pp),
               "provider_request_sha256": fingerprint, "serialized_payload_utf8_bytes": len(payload),
               "conservative_reservation_tokens": len(payload) + provider.WRAPPER_TOKENS + 8192}
        if ordinal <= 37:
            original_request = run / f"old/{ordinal:03d}/prepared_request.json"
            original_request.parent.mkdir(parents=True)
            original_request.write_bytes(rp.read_bytes())
            manifest = write(original_request.parent / "provider/manifest.json",
                {"status": "budget_exceeded", "external_model_calls": 0, "request_sha256": fingerprint})
            result = {"provider_status": "budget_exceeded", "physical_model_calls": 0,
                "request": dispatch._receipt(original_request), "provider_manifest": manifest,
                "public_input": packet_receipt, "method": "M1" if ordinal % 2 else "M2", "stage": 2}
            row.update(original_prepared_request=dispatch._receipt(original_request),
                       original_provider_manifest=manifest, original_result=write(original_request.parent / "result.json", result))
        else:
            condition, repeat = cells[ordinal - 38]
            row.update(condition=condition, repeat=repeat, fixed_pair_sha256="pair",
                       construction_provenance_only={"public_packet": packet_receipt})
        rows.append(row)
    data = {"schema": "tramask.continuation-budget-preflight.v02", "ledger": old_receipt,
            "prompt_builder": {"code": dispatch._receipt(Path(original_provider.__file__))},
            "provider_accounting": {"code": dispatch._receipt(Path(original_provider.__file__))},
            "mechanical_construction_amendment": {}, "requests": rows,
            "HF012_provenance": {"fixed_pair_sha256": "pair"}}
    freeze = {"schema": "tramask.continuation-freeze.v1", "status": "frozen",
        "output_root": str(run / "continuation_execution_test"), "baseline_ledger_snapshot": snapshot,
        "implementation": [dispatch._receipt(Path(m.__file__)) for m in [dispatch, provider, transport_adapter, variants, hypotheses]],
        "enrollments": {"HF012": {"status": "enrolled", "conditions": ["C1", "C2", "C3", "C4", "M1", "M2"],
                                   "shared_arms": {"M3": "C2", "M4": "C3"}}}}
    message = {"role": "user", "content": "SYNTHETIC UNIT TEST ONLY: authorize this temporary test budget."}
    auth = {"schema": "tramask.continuation-authorization.v1", "status": "approved",
        "authority": "explicit_user_authorization", "authorized_total_token_limit": 11_000_000,
        "run_dir": str(run), "approval_evidence": write(run / "synthetic_user_message.json", message),
        "user_answer": message["content"]}
    bundle = {"run": run, "data": data, "freeze": freeze, "auth": auth, "ledger_path": ledger_path}

    def bind():
        pre = write(run / "preflight.json", data)
        freeze["preflight"] = pre
        fr = write(run / "freeze.json", freeze)
        auth.update(preflight=pre, freeze=fr)
        ar = write(run / "synthetic_authorization.json", auth)
        bundle["receipts"] = (pre, fr, ar)
        return bundle["receipts"]

    bundle["bind"] = bind
    bind()
    current = copy.deepcopy(old)
    current["limit_tokens"] = 11_000_000
    write(ledger_path, current)  # External test fixture, never dispatcher behavior.
    return bundle


def stub_transport(calls):
    def call(project, run, out, request, max_tokens, *, authorization_receipt):
        calls.append(request["id"])
        raw, fingerprint = dispatch._payload(request)
        out = Path(out)
        out.mkdir(parents=True)
        ledger = provider.BudgetLedger(run, authorization_receipt)
        key = hashlib.sha256(str(out.resolve()).encode()).hexdigest()
        reserved, fresh = ledger.reserve(key, fingerprint, len(raw) + provider.WRAPPER_TOKENS, max_tokens)
        assert fresh and reserved is not None
        budget = ledger.settle(key, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        value = {"original_command": "python /tmp/check.py", "candidates": [
            {"rank": i, "status": "no_proposal", "reason": "Synthetic no proposal"} for i in range(1, 6)]}
        (out / "completion.txt").write_text(json.dumps(value))
        manifest = {"status": "complete", "external_model_calls": 1, "request_sha256": fingerprint, "budget": budget}
        write(out / "manifest.json", manifest)
        return manifest
    return call


def test_inspection_is_read_only_and_does_not_authorize(queue):
    before = queue["ledger_path"].read_bytes()
    context = dispatch.inspect_queue(*queue["receipts"][:2])
    assert context["dispatch_authorized"] is False
    assert not context["output_root"].exists()
    assert queue["ledger_path"].read_bytes() == before


@pytest.mark.parametrize("mode", ["old_authorization", "old_ledger", "wrong_new_ledger"])
def test_rejects_old_cap_and_authorization_ledger_disagreement(queue, monkeypatch, mode):
    calls = []
    monkeypatch.setattr(provider, "call", stub_transport(calls))
    if mode == "old_authorization":
        queue["auth"]["authorized_total_token_limit"] = 10_000_000
        queue["bind"]()
    else:
        ledger = json.loads(queue["ledger_path"].read_text())
        ledger["limit_tokens"] = 10_000_000 if mode == "old_ledger" else 12_000_000
        write(queue["ledger_path"], ledger)
    with pytest.raises(ValueError, match="increase_above_original_cap|authorized_ledger_limit_mismatch"):
        dispatch.dispatch(*queue["receipts"], project_root=queue["run"])
    assert calls == []
    assert not Path(queue["freeze"]["output_root"]).exists()


def test_rejects_original_task_that_already_called_provider(queue, monkeypatch):
    row = queue["data"]["requests"][0]
    mp = Path(row["original_provider_manifest"]["path"])
    manifest = json.loads(mp.read_text())
    manifest.update(status="error", external_model_calls=1)
    row["original_provider_manifest"] = write(mp, manifest)
    rp = Path(row["original_result"]["path"])
    result = json.loads(rp.read_text())
    result.update(provider_manifest=row["original_provider_manifest"], provider_status="error", physical_model_calls=1)
    row["original_result"] = write(rp, result)
    queue["bind"]()
    calls = []
    monkeypatch.setattr(provider, "call", stub_transport(calls))
    with pytest.raises(ValueError, match="not_zero_call_budget_refusal"):
        dispatch.dispatch(*queue["receipts"], project_root=queue["run"])
    assert not calls


def test_tampered_request_or_missing_HF012_enrollment_rejected(queue):
    queue["freeze"]["enrollments"] = {}
    queue["bind"]()
    with pytest.raises(ValueError, match="HF012_enrollment"):
        dispatch.inspect_queue(*queue["receipts"][:2])


def test_request_byte_tampering_is_rejected_before_output(queue):
    path = Path(queue["data"]["requests"][0]["prepared_request"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="receipt_mismatch"):
        dispatch.dispatch(*queue["receipts"], project_root=queue["run"])
    assert not Path(queue["freeze"]["output_root"]).exists()


def test_serial49_exact_requests_shared_arms_and_completed_resume(queue, monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "call", stub_transport(calls))
    report = dispatch.dispatch(*queue["receipts"], project_root=queue["run"])
    assert calls == [f"synthetic/request/{i}" for i in range(1, 50)]
    assert report["charged_tokens_this_invocation"] == 49 * 15
    assert report["shared_arms_extra_calls"] == 0
    out = Path(queue["freeze"]["output_root"])
    for row in queue["data"]["requests"]:
        attempt = out / f'{row["queue_ordinal"]:03d}'
        assert (attempt / "prepared_request.json").read_bytes() == Path(row["prepared_request"]["path"]).read_bytes()
        if row["category"] != "HS005_reference_completion":
            slots = json.loads((attempt / "candidate_slots.json").read_text())
            assert slots["n_registered_slots"] == slots["n_no_proposal"] == 5
    assert json.loads((out / "037/result.json").read_text())["reference_replaced"] is False
    again = dispatch.dispatch(*queue["receipts"], project_root=queue["run"])
    assert len(calls) == 49 and again["new_physical_calls_known"] == 0
    assert again["charged_tokens_this_invocation"] == 0


def test_partial_attempt_never_redispatched_and_remaining_queue_can_continue(queue, monkeypatch):
    calls = []
    def fail(*args, **kwargs):
        calls.append(args[3]["id"])
        raise RuntimeError("synthetic interrupted transport")
    monkeypatch.setattr(provider, "call", fail)
    first = dispatch.dispatch(*queue["receipts"], project_root=queue["run"])
    assert first["calls_with_unknown_physical_count"] == 1
    monkeypatch.setattr(provider, "call", stub_transport(calls))
    second = dispatch.dispatch(*queue["receipts"], project_root=queue["run"])
    assert calls.count("synthetic/request/1") == 1
    assert second["new_physical_calls_known"] == 48
    assert second["requests"][0]["status"] == "existing_attempt_not_redispatched"


def test_insufficient_authorized_headroom_stops_without_trying_smaller_requests(queue, monkeypatch):
    cap = 10_000_001
    queue["auth"]["authorized_total_token_limit"] = cap
    queue["bind"]()
    ledger = json.loads(queue["ledger_path"].read_text())
    ledger["limit_tokens"] = cap
    # Original snapshot remains intact; an earlier permitted reservation consumes headroom.
    row = queue["data"]["requests"][-1]
    out = Path(queue["freeze"]["output_root"]) / "049/provider"
    key = hashlib.sha256(str(out).encode()).hexdigest()
    ledger["calls"][key] = {"request_sha256": row["provider_request_sha256"], "status": "reserved", "reserved_tokens": 31590}
    write(queue["ledger_path"], ledger)
    calls = []
    monkeypatch.setattr(provider, "call", stub_transport(calls))
    result = dispatch.dispatch(*queue["receipts"], project_root=queue["run"])
    assert not calls
    assert result["requests"] == [{"queue_ordinal": 1, "status": "budget_unavailable_queue_stopped", "new_physical_calls": 0}]
    assert result["spent_after"] <= cap


def test_adapter_revalidates_authorization_at_settlement_and_never_updates_cap(queue):
    ledger = provider.BudgetLedger(queue["run"], queue["receipts"][2])
    entry, fresh = ledger.reserve("synthetic", "f" * 64, 100, 10)
    assert fresh and entry["reserved_tokens"] == 110
    before = json.loads(queue["ledger_path"].read_text())
    ap = Path(queue["receipts"][2]["path"])
    ap.write_text(ap.read_text() + " ")
    with pytest.raises(ValueError, match="receipt_mismatch"):
        ledger.settle("synthetic", {"total_tokens": 1})
    after = json.loads(queue["ledger_path"].read_text())
    assert after == before
    assert after["limit_tokens"] == 11_000_000
    assert original_provider.BUDGET_TOKENS == 10_000_000


def test_default_cli_does_not_dispatch(queue, monkeypatch, capsys):
    refs = []
    for i, receipt in enumerate(queue["receipts"][:2]):
        p = queue["run"] / f"receipt_arg_{i}.json"
        write(p, receipt)
        refs.append(str(p))
    calls = []
    monkeypatch.setattr(provider, "call", stub_transport(calls))
    assert dispatch.main(["--preflight-receipt", refs[0], "--freeze-receipt", refs[1]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified_not_dispatched"
    assert not calls
