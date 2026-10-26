"""Versioned continuation provider; externally authorized cap, same one-attempt transport.

Every physical request reserves a conservative bound before dispatch. A killed
process leaves its reservation charged against the budget; resuming never sends
the same output directory again. Transport failures and missing usage cost the
full reservation. Credentials and endpoint URLs are excluded from artifacts.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

import httpx

from augmentation.provider import connection

MODEL = "deepseek-v4-flash"
BUDGET_TOKENS = 10_000_000
WRAPPER_TOKENS = 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _atomic_write(path, value):
    path = Path(path)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(_encoded(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _usage_tokens(usage):
    """Trust a complete token pair or a provider total, never a partial pair."""
    if not isinstance(usage, dict):
        return None
    valid = lambda value: type(value) is int and value >= 0
    counts = []
    if valid(usage.get("total_tokens")):
        counts.append(usage["total_tokens"])
    if valid(usage.get("prompt_tokens")) and valid(usage.get("completion_tokens")):
        counts.append(usage["prompt_tokens"] + usage["completion_tokens"])
    return max(counts) if counts else None


def read_receipt(receipt):
    """Read one exact externally bound artifact; never infer approval."""
    if not isinstance(receipt, dict) or not {"path", "bytes", "sha256"} <= receipt.keys():
        raise ValueError("artifact_receipt_required")
    path = Path(receipt["path"])
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("noncanonical_receipt_path")
    raw = path.read_bytes()
    if type(receipt["bytes"]) is not int or len(raw) != receipt["bytes"] or hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
        raise ValueError("artifact_receipt_mismatch")
    return raw


def validate_authorization(run_dir, receipt):
    """Explicit user authorization and its preflight/freeze bindings are mandatory.

    Authorization schema: tramask.continuation-authorization.v1, status approved,
    authority explicit_user_authorization, authorized_total_token_limit, run_dir,
    preflight/freeze/approval_evidence receipts, and user_answer. approval_evidence
    is the externally recorded JSON user message {role: user, content: ...}.
    This code verifies the record, not the human provenance of an invented file.
    """
    auth = json.loads(read_receipt(receipt))
    if (auth.get("schema") != "tramask.continuation-authorization.v1"
            or auth.get("status") != "approved"
            or auth.get("authority") != "explicit_user_authorization"):
        raise ValueError("explicit_budget_authorization_required")
    cap = auth.get("authorized_total_token_limit")
    if type(cap) is not int or cap <= BUDGET_TOKENS:
        raise ValueError("continuation_requires_explicit_increase_above_original_cap")
    if auth.get("run_dir") != str(Path(run_dir).absolute()):
        raise ValueError("authorization_run_mismatch")
    message = json.loads(read_receipt(auth.get("approval_evidence")))
    if (message.get("role") != "user" or not isinstance(message.get("content"), str)
            or not message["content"].strip() or message["content"] != auth.get("user_answer")):
        raise ValueError("explicit_user_message_receipt_required")
    preflight = json.loads(read_receipt(auth.get("preflight")))
    freeze = json.loads(read_receipt(auth.get("freeze")))
    if (freeze.get("schema") != "tramask.continuation-freeze.v1"
            or freeze.get("status") != "frozen" or freeze.get("preflight") != auth["preflight"]
            or preflight.get("schema") != "tramask.continuation-budget-preflight.v02"):
        raise ValueError("authorization_freeze_preflight_mismatch")
    return auth


class BudgetLedger:
    """The run directory must be shared by all conditions and calibration calls."""

    def __init__(self, run_dir, authorization_receipt):
        validate_authorization(run_dir, authorization_receipt)
        self.authorization_receipt = authorization_receipt
        self.root = Path(run_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "provider_budget.json"

    @contextmanager
    def _locked(self):
        with (self.root / "provider_budget.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                ledger = json.loads(self.path.read_text()) if self.path.exists() else {
                    "version": 1, "limit_tokens": BUDGET_TOKENS, "calls": {}}
                authorization = validate_authorization(self.root, self.authorization_receipt)
                if ledger["limit_tokens"] != authorization["authorized_total_token_limit"]:
                    raise ValueError("authorized_ledger_limit_mismatch")
                yield ledger
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def _committed(ledger):
        return sum(entry.get("charged_tokens", entry["reserved_tokens"]) for entry in ledger["calls"].values())

    def reserve(self, key, fingerprint, input_bound, output_cap):
        with self._locked() as ledger:
            if key in ledger["calls"]:
                entry = ledger["calls"][key]
                if entry["request_sha256"] != fingerprint:
                    raise ValueError("out_dir_request_mismatch")
                return dict(entry), False
            amount = input_bound + output_cap
            if self._committed(ledger) + amount > ledger["limit_tokens"]:
                return None, False
            entry = {"request_sha256": fingerprint, "input_token_upper_bound": input_bound,
                     "output_token_cap": output_cap, "reserved_tokens": amount, "status": "reserved"}
            ledger["calls"][key] = entry
            _atomic_write(self.path, ledger)
            return dict(entry), True

    def settle(self, key, usage):
        with self._locked() as ledger:
            entry = ledger["calls"][key]
            if entry["status"] == "settled":
                return dict(entry)
            known = _usage_tokens(usage)
            entry.update(status="settled", charged_tokens=entry["reserved_tokens"] if known is None else known,
                         accounting="full_reservation_missing_usage" if known is None else "provider_usage")
            if known is not None and known > entry["reserved_tokens"]:
                entry["usage_exceeded_reservation"] = True
            _atomic_write(self.path, ledger)
            return dict(entry)

    def snapshot(self):
        with self._locked() as ledger:
            return {**ledger, "committed_tokens": self._committed(ledger)}


class _RedactedStream:
    """Redact even when a credential is split across response chunks."""

    def __init__(self, stream, secrets):
        secrets = sorted({value.encode() for value in secrets if value}, key=len, reverse=True)
        self.stream = stream
        self.pattern = re.compile(b"|".join(re.escape(value) for value in secrets)) if secrets else None
        self.keep = max(map(len, secrets), default=1) - 1
        self.tail = b""

    def write(self, chunk, final=False):
        data = self.tail + chunk
        boundary = len(data) if final else max(0, len(data) - self.keep)
        position = 0
        if self.pattern:
            for match in self.pattern.finditer(data):
                if match.start() >= boundary:
                    break
                self.stream.write(data[position:match.start()] + b"[REDACTED]")
                position = match.end()
        if position < boundary:
            self.stream.write(data[position:boundary])
            position = boundary
        self.tail = data[position:]
        self.stream.flush()


def call(root, run_dir, out_dir, request, max_tokens=8192, *, authorization_receipt):
    """Return a manifest with ``parsed`` JSON or error metadata; never retry.

    ``request`` contains string fields ``id``, ``system``, and ``prompt``.
    Passing an existing output directory returns the recorded call. A different
    request for that directory raises ValueError instead of overwriting evidence.
    """
    validate_authorization(run_dir, authorization_receipt)
    if type(max_tokens) is not int or max_tokens <= 0:
        raise ValueError("invalid_max_tokens")
    if any(not isinstance(request.get(field), str) for field in ("id", "system", "prompt")):
        raise ValueError("request_requires_id_system_prompt_strings")
    payload = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
               "messages": [{"role": "system", "content": request["system"]},
                            {"role": "user", "content": request["prompt"]}],
               "response_format": {"type": "json_object"}, "stream": False,
               "thinking": {"type": "disabled"}}
    body = _encoded(payload)
    fingerprint = hashlib.sha256(_encoded({"id": request["id"], "payload": payload})).hexdigest()
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous.get("request_sha256") != fingerprint:
            raise ValueError("out_dir_request_mismatch")
        return {**previous, "resumed": True}
    record = {"version": "tramask-provider-continuation.v1", "authorization_receipt": authorization_receipt, "request_id": request["id"], "model": MODEL,
              "request_sha256": fingerprint, "created_at": datetime.now(timezone.utc).isoformat(),
              "external_model_calls": 0, "status": "prepared", "timeout_seconds": 600,
              "retry_policy": "one_attempt", "parsed": None}
    try:
        endpoint, credential = connection(Path(root))
    except Exception as exc:
        record.update(status="error", error_type=type(exc).__name__, error_code="provider_configuration")
        _atomic_write(manifest_path, record)
        return record
    ledger = BudgetLedger(run_dir, authorization_receipt)
    budget_key = hashlib.sha256(str(output.resolve()).encode()).hexdigest()
    reservation, fresh = ledger.reserve(budget_key, fingerprint, len(body) + WRAPPER_TOKENS, max_tokens)
    if reservation is None:
        record.update(status="budget_exceeded", error_code="insufficient_uncommitted_tokens")
        _atomic_write(manifest_path, record)
        return record
    if not fresh:
        if manifest_path.exists():
            return {**json.loads(manifest_path.read_text()), "resumed": True}
        return {**record, "status": "interrupted", "error_code": "existing_reservation_no_redispatch",
                "budget": reservation, "resumed": True}
    record.update(budget_key=budget_key, budget=reservation,
                  endpoint_sha256=hashlib.sha256(endpoint.encode()).hexdigest())
    # Normally prompts contain no credentials; protect artifacts if they do.
    recorded_body = body
    for secret in (credential, endpoint):
        recorded_body = recorded_body.replace(secret.encode(), b"[REDACTED]")
    (output / "request.json").write_bytes(recorded_body + b"\n")
    _atomic_write(manifest_path, record)
    started = time.monotonic()
    usage = None
    try:
        record.update(status="dispatching", external_model_calls=1)
        _atomic_write(manifest_path, record)
        with (output / "response.body").open("wb") as raw_stream:
            redactor = _RedactedStream(raw_stream, (credential, endpoint))
            received = 0
            try:
                with httpx.Client(timeout=600, follow_redirects=False) as client:
                    with client.stream("POST", endpoint,
                                       headers={"Authorization": "Bearer " + credential,
                                                "Content-Type": "application/json"}, content=body) as response:
                        record["http_status"] = response.status_code
                        for chunk in response.iter_bytes():
                            received += len(chunk)
                            if received > MAX_RESPONSE_BYTES:
                                raise ValueError("response_byte_limit")
                            redactor.write(chunk)
            finally:
                redactor.write(b"", final=True)
                os.fsync(raw_stream.fileno())
        raw = json.loads((output / "response.body").read_bytes())
        if not isinstance(raw, dict):
            raise ValueError("response_not_object")
        _atomic_write(output / "response.json", raw)
        usage = raw.get("usage")
        record.update(response_model=raw.get("model"), usage=usage)
        if not 200 <= record["http_status"] < 300:
            raise ValueError("http_status_error")
        choice = raw["choices"][0]
        record["finish_reason"] = choice.get("finish_reason")
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("missing_content")
        (output / "completion.txt").write_text(content)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("completion_not_json_object")
        record.update(parsed=parsed, status="complete" if choice.get("finish_reason") == "stop" else "incomplete")
    except Exception as exc:
        record.update(status="error", error_type=type(exc).__name__)
        # Messages from network libraries may contain the URL or credential.
        if type(exc) is ValueError and str(exc) in {
            "response_byte_limit", "response_not_object", "http_status_error", "missing_content",
            "completion_not_json_object"}:
            record["error_code"] = str(exc)
    finally:
        record["budget"] = ledger.settle(budget_key, usage)
        record["seconds"] = time.monotonic() - started
        response_path = output / "response.body"
        if response_path.exists():
            record["response_sha256"] = hashlib.sha256(response_path.read_bytes()).hexdigest()
        _atomic_write(manifest_path, record)
    return record
