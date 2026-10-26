"""Lossless sharing of repeated complete test-file contents in model inputs.

No test, version, command, selector, source byte or evidence reference is
discarded. Decoding reconstructs the exact pre-encoding payload.
"""
import copy
import hashlib
from collections import Counter


def _ref(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunks(text):
    result, current = [], []
    for line in text.splitlines(keepends=True):
        current.append(line)
        if not line.strip():
            result.append("".join(current))
            current = []
    if current:
        result.append("".join(current))
    return result


def encode_payload(payload):
    result = copy.deepcopy(payload)
    material = result.get("material", {})
    tests = list(material.get("validation_tests", []))
    if "selected_test" in material:
        tests.append(material["selected_test"])
    texts = [text for test in tests for text in test.get("files", {}).values() if isinstance(text, str)]
    repeated = {text for text, count in Counter(texts).items() if count > 1}
    chunks = {text: _chunks(text) for text in set(texts)}
    chunk_counts = Counter(chunk for parts in chunks.values() for chunk in parts if len(chunk.encode()) >= 256)
    shared_chunks = {chunk for chunk, count in chunk_counts.items() if count > 1}
    if not repeated and not shared_chunks:
        return result
    eligible = repeated | {text for text, parts in chunks.items() if any(chunk in shared_chunks for chunk in parts)}
    shared = {_ref(text): ({"chunks": [{"$text_chunk": _ref(part)} if part in shared_chunks else part
                                      for part in chunks[text]]} if any(part in shared_chunks for part in chunks[text]) else text)
              for text in eligible}
    if len(shared) != len(eligible):
        raise ValueError("Unexpected file-content hash collision")
    for test in tests:
        for path, text in test.get("files", {}).items():
            if isinstance(text, str) and text in eligible:
                test["files"][path] = {"$file_content": _ref(text)}
    result["shared_file_contents"] = shared
    if shared_chunks:
        result["shared_text_chunks"] = {_ref(chunk): chunk for chunk in shared_chunks}
    result["file_content_encoding"] = {
        "version": "exact-test-file-sharing.v2",
        "lookup": "A files[path] $file_content reference resolves through shared_file_contents. A string is the complete file. For a chunks array, concatenate its elements in order with no added characters; a $text_chunk element resolves to its exact string in shared_text_chunks. Blank lines and indentation are already included. This reconstructs every complete original file. Use reconstructed text for reading and exact edits. Every test ID, version, command, selector and path is retained.",
        "lossless": True}
    return result


def decode_payload(payload):
    result = copy.deepcopy(payload)
    if "file_content_encoding" not in result:
        return result
    if result.pop("file_content_encoding")["version"] not in {"exact-test-file-sharing.v1", "exact-test-file-sharing.v2"}:
        raise ValueError("Unknown file-content encoding")
    shared = result.pop("shared_file_contents")
    chunks = result.pop("shared_text_chunks", {})
    if any(_ref(text) != key for key, text in chunks.items()):
        raise ValueError("Shared chunk hash mismatch")
    shared = {key: ("".join(chunks[item["$text_chunk"]] if isinstance(item, dict) else item for item in value["chunks"])
                    if isinstance(value, dict) else value) for key, value in shared.items()}
    if any(_ref(text) != key for key, text in shared.items()):
        raise ValueError("Shared content hash mismatch")
    material = result["material"]
    tests = list(material.get("validation_tests", []))
    if "selected_test" in material:
        tests.append(material["selected_test"])
    for test in tests:
        for path, value in test.get("files", {}).items():
            if isinstance(value, dict) and set(value) == {"$file_content"}:
                test["files"][path] = shared[value["$file_content"]]
    return result
