"""Copied as sitecustomize.py for opt-in, isolated Python test runs.

Only selected source lines and selected data paths are recorded. Values are
read without evaluating subject expressions or calling their repr/property
methods. Other languages retain explicit 'activation unavailable' feedback.
"""
import atexit
import json
import os
import sys
import threading


def install():
    config_path = os.environ.get("AUGMENTATION_TRACE_CONFIG")
    if not config_path:
        return
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)
    probes = {}
    for probe in config["probes"]:
        filename = os.path.abspath(os.path.join(config["repository"], probe["path"]))
        probes.setdefault(filename, {}).setdefault(probe["line"], []).append(probe)
    output = open(config["output"], "a", encoding="utf-8", buffering=1)
    output.write(json.dumps({"event": "trace_started", "pid": os.getpid()}) + "\n")
    lock = threading.Lock()
    frames, seen = {}, set()
    counter, samples = 0, 0

    def snapshot(value, depth=0):
        if value is None or type(value) in {bool, int, float}:
            return {"known": True, "value": value}
        if type(value) is str:
            return {"known": len(value) <= 200, "value": value[:200]}
        if type(value) is dict and depth < 2 and len(value) <= 12 and all(type(k) is str for k in value):
            items = {k: snapshot(v, depth + 1) for k, v in value.items()}
            return {"known": all(v["known"] for v in items.values()),
                    "value": {k: v.get("value") for k, v in items.items() if v["known"]},
                    "present_fields": list(value), "object_id": id(value)}
        return {"known": False, "object_id": id(value)}

    def read(frame, path):
        parts = path.split(".")
        if parts[0] not in frame.f_locals:
            return {"known": False}
        value = frame.f_locals[parts[0]]
        for field in parts[1:]:
            if type(value) is dict:
                fields = value
            else:
                try:
                    fields = object.__getattribute__(value, "__dict__")
                except (AttributeError, TypeError):
                    return {"known": False}
                if type(fields) is not dict:
                    return {"known": False}
            if field not in fields:
                return {"known": False, "present": False}
            value = fields[field]
        return {**snapshot(value), "present": True}

    def trace(frame, event, arg):
        nonlocal counter, samples
        locations = probes.get(frame.f_code.co_filename)
        if locations is None:
            return None
        frame_id = id(frame)
        if event == "call":
            counter += 1
            parent = frame.f_back
            entry = counter
            test = None
            while parent is not None:
                if id(parent) in frames:
                    entry = frames[id(parent)]["entry"]
                    break
                if parent.f_code.co_name.startswith("test_"):
                    test = parent.f_code.co_name
                parent = parent.f_back
            frames[frame_id] = {"invocation": counter, "entry": entry, "test": test}
        if event == "line" and samples < config.get("max_events", 2000):
            for probe in locations.get(frame.f_lineno, []):
                values = {path: read(frame, path) for path in probe.get("reads", [])[:12]}
                identity = (probe["id"], json.dumps(values, sort_keys=True), frames.get(frame_id, {}).get("invocation"))
                if identity in seen:
                    continue
                seen.add(identity)
                samples += 1
                record = {"event": "probe", "probe_id": probe["id"], "path": probe["path"], "line": frame.f_lineno,
                          "function": frame.f_code.co_name, "values": values, "pid": os.getpid(), **frames.get(frame_id, {})}
                with lock:
                    output.write(json.dumps(record, ensure_ascii=True) + "\n")
        if event == "return":
            frames.pop(frame_id, None)
        return trace

    def finish():
        sys.settrace(None)
        threading.settrace(None)
        output.write(json.dumps({"event": "trace_finished", "pid": os.getpid(), "samples": samples,
                                 "truncated": samples >= config.get("max_events", 2000)}) + "\n")
        output.close()

    def safe_trace(frame, event, arg):
        try:
            return safe_trace if trace(frame, event, arg) is not None else None
        except Exception:
            return None

    atexit.register(finish)
    threading.settrace(safe_trace)
    sys.settrace(safe_trace)


try:
    install()
except Exception:
    # A probe startup failure must not change the test's expected behavior.
    # The parent detects the absent start/finish receipts and marks it unknown.
    pass
