"""Recorded provider transport with an explicit model identifier.

The older experiment transport remains unchanged. Endpoint and credentials
come from the authorized .env file and are never written to experiment logs.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from dotenv import dotenv_values
import httpx

MODEL = "deepseek-v4-flash"


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def write(path, value):
    Path(path).write_bytes(encoded(value) + b"\n")


def connection(root):
    config = {k.lower(): v for k, v in dotenv_values(root / ".env").items() if v}
    base = config.get("base_url") or config.get("openai_base_url")
    key = config.get("api_key") or config.get("openai_api_key")
    if not base or not key:
        raise ValueError("missing_provider_configuration")
    route = root / "results/api_route.json"
    prefix = json.loads(route.read_text()).get("prefix", "") if route.exists() else ""
    suffix = urlsplit(base).path.rstrip("/")
    if suffix.endswith("/v1") or suffix.endswith("/chat/completions"):
        prefix = ""
    endpoint = base.rstrip("/") if suffix.endswith("/chat/completions") else base.rstrip("/") + "/" + prefix + "chat/completions"
    return endpoint, key


def discover(root, output):
    endpoint, key = connection(root)
    url = endpoint.removesuffix("chat/completions") + "models"
    result = {"requested_model": MODEL, "endpoint_sha256": hashlib.sha256(endpoint.encode()).hexdigest()}
    try:
        response = httpx.get(url, headers={"Authorization": "Bearer " + key}, timeout=60, follow_redirects=False)
        result["http_status"] = response.status_code
        response.raise_for_status()
        result["deepseek_models"] = [r for r in response.json().get("data", []) if "deepseek" in r.get("id", "").lower()]
        result["requested_id_listed"] = any(r["id"].lower() == MODEL for r in result["deepseek_models"])
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        result["error_type"] = type(exc).__name__
    write(output, result)
    return result


def dispatch(request, output, *, root, model=MODEL):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    payload = {"model": model, "temperature": 0, "max_tokens": request.get("max_tokens", 16384),
               "messages": [{"role": "system", "content": request["system"]}, {"role": "user", "content": request["prompt"]}],
               "response_format": {"type": "json_object"}, "stream": False,
               "thinking": {"type": request.get("thinking", "enabled")},
               "reasoning_effort": request.get("reasoning_effort", "high")}
    write(output / "request.json", payload)
    record = {"version": "explicit-model-provider.v1", "request_id": request["id"], "model": model,
              "request_sha256": hashlib.sha256(encoded(payload)).hexdigest(),
              "created_at": datetime.now(timezone.utc).isoformat(), "external_model_calls": 0,
              "status": "prepared", "timeout_seconds": 600, "retry_policy": "one_attempt",
              "manual_labels_included": False, "reference_or_verifier_inputs": False}
    write(output / "manifest.json", record)
    started = time.monotonic()
    body = bytearray()
    try:
        endpoint, key = connection(root)
        record.update(endpoint_sha256=hashlib.sha256(endpoint.encode()).hexdigest(), status="dispatching", external_model_calls=1)
        write(output / "manifest.json", record)
        with httpx.Client(timeout=600, follow_redirects=False) as client:
            with client.stream("POST", endpoint, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                               content=encoded(payload)) as response:
                record["http_status"] = response.status_code
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > 4 * 1024 * 1024:
                        raise ValueError("response_byte_limit")
                    body.extend(chunk)
                response.raise_for_status()
        raw = json.loads(body)
        write(output / "response.json", raw)
        choice = raw["choices"][0]
        record.update(response_model=raw.get("model"), finish_reason=choice.get("finish_reason"), usage=raw.get("usage"))
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("missing_content")
        (output / "completion.txt").write_text(content)
        record["status"] = "complete" if choice.get("finish_reason") == "stop" else "incomplete"
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        record.update(status="error", error_type=type(exc).__name__)
    finally:
        (output / "response.body").write_bytes(body)
        record.update(seconds=time.monotonic() - started, response_sha256=hashlib.sha256(body).hexdigest())
        write(output / "manifest.json", record)
    return record
