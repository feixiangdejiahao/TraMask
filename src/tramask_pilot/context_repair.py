"""Preserve the historical test context when transplanting the submitted P.

This repairs replay machinery, not a test or a scientific masking factor.  The
functions that inspect/build archives never execute subjects.  Only an explicit
``recover_final_context`` call creates a container and reruns the reviewed test.
No historical evidence, checkpoint, or previous result directory is replaced.
"""
from __future__ import annotations

import ast
import copy
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import tarfile
import uuid

from .corpus import RUN


TEST_COMPONENTS = frozenset({"test", "tests", "fixtures", "__tests__", "__fixtures__", "testdata"})
BLOCKED_COMPONENTS = frozenset({
    ".git", ".aws", ".codex", ".agents", ".venv", "venv", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".cache",
})
PRODUCTION_EXTENSIONS = frozenset({
    ".py", ".go", ".rs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".java", ".cs", ".rb", ".php",
    ".swift", ".kt", ".scala",
})


def _name(value, *, repository_relative=False):
    """Return one canonical app/... or tmp/... file name, never normalize '..'."""
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise ValueError("invalid_subject_path")
    absolute = value.startswith("/")
    raw = value[1:] if absolute else value
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("noncanonical_subject_path")
    if not absolute and (repository_relative or parts[0] not in {"app", "tmp"}):
        parts.insert(0, "app")
    if len(parts) < 2 or parts[0] not in {"app", "tmp"}:
        raise ValueError("subject_path_outside_app_or_tmp")
    return "/".join(parts)


def _blocked(name):
    return any(part in BLOCKED_COMPONENTS or part == ".env" or part.startswith(".env.")
               for part in PurePosixPath(name).parts)


def test_context_reasons(path, test_paths=(), *, repository_relative=False):
    """Classify by names only; do not inspect file contents or evaluator labels."""
    name = _name(path, repository_relative=repository_relative)
    if _blocked(name):
        return []
    explicit = {_name(value) for value in test_paths}
    parts = PurePosixPath(name).parts
    base = parts[-1]
    lower = base.lower()
    reasons = []
    if any(name == value or name.startswith(value + "/") for value in explicit):
        reasons.append("explicit_selected_test_path")
    if any(part.lower() in TEST_COMPONENTS for part in parts[1:-1]):
        reasons.append("conventional_test_or_fixture_directory")
    if (lower in {"conftest.py", "test.py", "tests.py"}
            or lower.startswith("test_") or lower.startswith("tests_")
            or re.search(r"(?:^|[._-])(?:test|tests|spec)\.[^.]+$", lower)
            or re.search(r"(?:Test|Tests|Spec)\.(?:java|kt|scala|cs)$", base)
            or re.fullmatch(r"Test[A-Z][A-Za-z0-9_]*\.(?:java|kt|scala|cs)", base)):
        reasons.append("conventional_test_filename")
    return reasons


def is_test_context_path(path, test_paths=(), *, repository_relative=False):
    return bool(test_context_reasons(path, test_paths, repository_relative=repository_relative))


def test_paths_with_addendum(case_directory, test_paths):
    """Read an explicit context-path addendum without changing test selection."""
    paths = list(dict.fromkeys("/" + _name(path) for path in test_paths))
    addendum_path = Path(case_directory) / "localization/test_context_addendum.json"
    if not addendum_path.exists():
        return paths, None
    if addendum_path.is_symlink() or not addendum_path.is_file():
        raise ValueError("test_context_addendum_not_regular_file")
    value = _read(addendum_path)
    additions = value.get("additional_test_paths")
    if (not isinstance(additions, list) or not isinstance(value.get("reason"), str)
            or not value["reason"].strip()):
        raise ValueError("invalid_test_context_addendum")
    for path in additions:
        if not isinstance(path, str) or not path.startswith(("/app/", "/tmp/")):
            raise ValueError("additional_test_path_must_be_absolute")
        name = _name(path)
        if _blocked(name):
            raise ValueError("additional_test_path_blocked")
        if "/" + name not in paths:
            paths.append("/" + name)
    return paths, _receipt(addendum_path)


def classify_historical_additions(paths, *, baseline_untracked=(), test_paths=()):
    """Separate cleanup candidates from tests, dependencies, and unknown files.

    ``paths`` and ``baseline_untracked`` are repository-relative Git paths.
    Only known production extensions can enter ``production_to_remove``.
    """
    baseline = {_name(p, repository_relative=True) for p in baseline_untracked if p}
    result = {"production_to_remove": [], "test_context_to_preserve": [],
              "baseline_to_preserve": [], "other_to_preserve": []}
    for path in dict.fromkeys(p for p in paths if p):
        name = _name(path, repository_relative=True)
        if name in baseline or _blocked(name):
            key = "baseline_to_preserve"
        elif is_test_context_path(name, test_paths):
            key = "test_context_to_preserve"
        elif PurePosixPath(name).suffix.lower() in PRODUCTION_EXTENSIONS:
            key = "production_to_remove"
        else:
            key = "other_to_preserve"
        result[key].append(path)
    return result


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _receipt(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}


def _read(path):
    return json.loads(Path(path).read_text())


def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _verify_receipt(record, *, within=None):
    path = Path(record["path"])
    if path.is_symlink() or not path.is_file():
        raise ValueError("receipt_not_regular_file")
    path = path.resolve()
    if within is not None and not path.is_relative_to(Path(within).resolve()):
        raise ValueError("receipt_outside_case")
    if _receipt(path) != {"path": str(path), "bytes": record["bytes"], "sha256": record["sha256"]}:
        raise ValueError("receipt_hash_or_size_mismatch")
    return path


def build_test_context_archive(historical_archive, output, *, test_paths=(),
                               manifest_path=None, absent_paths=(),
                               max_file_bytes=256 * 1024 * 1024,
                               max_total_bytes=2 * 1024 * 1024 * 1024,
                               max_members=200_000):
    """Create a new regular-file-only tar from verified historical members.

    No archive member is extracted onto the host. Names, duplicate entries,
    sizes and (when supplied) snapshot hashes are validated. New TarInfo objects
    discard link targets, owners, extended metadata and special permission bits.
    The receipt lists every preserved file, excluded nonregular context member,
    and historical absence. Explicit selected tests must be present and regular.
    """
    archive = Path(historical_archive).resolve(strict=True)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    explicit = list(dict.fromkeys(_name(p) for p in test_paths))
    if any(_blocked(p) for p in explicit):
        raise ValueError("selected_test_in_blocked_path")
    manifest = _read(manifest_path) if manifest_path else None
    manifest_rows = {}
    if manifest:
        for row in manifest.get("files", []):
            name = _name(row["path"])
            if name in manifest_rows:
                raise ValueError("duplicate_snapshot_manifest_path")
            manifest_rows[name] = row
    absent = {_name(p) for p in absent_paths}
    absent.update(name for name, row in manifest_rows.items()
                  if row.get("kind") == "missing" and is_test_context_path(name, explicit))
    if any(not is_test_context_path(p, explicit) for p in absent):
        raise ValueError("historical_absence_outside_test_context")
    archive_receipt = _receipt(archive)
    output.mkdir(parents=True, exist_ok=False)
    safe_archive = output / "test_context.tar.gz"
    partial = output / "test_context.tar.gz.partial"
    records, excluded, seen = [], [], set()
    spent = 0
    try:
        with tarfile.open(archive, "r:*") as source, partial.open("xb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as target:
                    for ordinal, member in enumerate(source):
                        if ordinal >= max_members:
                            raise ValueError("historical_archive_member_limit")
                        # Directory headers are never copied, but their names must also be safe.
                        candidate = member.name.rstrip("/") if member.isdir() else member.name
                        if candidate in {"app", "tmp"} and member.isdir():
                            continue
                        name = _name(candidate)
                        if member.name.startswith("/") or name != candidate:
                            raise ValueError("noncanonical_archive_member")
                        if name in seen:
                            raise ValueError("duplicate_archive_member")
                        seen.add(name)
                        reasons = test_context_reasons(name, explicit)
                        if not reasons:
                            continue
                        if not member.isfile() or member.issym() or member.islnk():
                            if not member.isdir():
                                excluded.append({"subject_path": "/" + name,
                                                 "reason": "nonregular_historical_test_context"})
                            continue
                        if (member.size < 0 or member.size > max_file_bytes
                                or spent + member.size > max_total_bytes):
                            raise ValueError("historical_test_context_size_limit")
                        row = manifest_rows.get(name)
                        if manifest is not None and (not row or row.get("kind") != "file"
                                or row.get("bytes") != member.size):
                            raise ValueError("historical_test_context_manifest_mismatch:" + name)
                        stream = source.extractfile(member)
                        if stream is None:
                            raise ValueError("historical_test_context_unreadable:" + name)
                        # One selected file is bounded; bytes never become a host filesystem path.
                        with stream:
                            data = stream.read(max_file_bytes + 1)
                        if len(data) != member.size:
                            raise ValueError("historical_test_context_size_mismatch:" + name)
                        digest = hashlib.sha256(data).hexdigest()
                        if row is not None and row.get("sha256") != digest:
                            raise ValueError("historical_test_context_hash_mismatch:" + name)
                        safe = tarfile.TarInfo(name)
                        safe.size, safe.mode = len(data), member.mode & 0o777
                        safe.uid = safe.gid = safe.mtime = 0
                        target.addfile(safe, io.BytesIO(data))
                        records.append({"subject_path": "/" + name, "archive_path": name,
                                        "bytes": len(data), "sha256": digest, "mode": safe.mode,
                                        "original_mode": member.mode, "selection_reasons": reasons})
                        spent += len(data)
        selected = {row["archive_path"] for row in records}
        if any(path not in selected and not any(p.startswith(path + "/") for p in selected)
               for path in explicit):
            raise ValueError("explicit_selected_test_missing_or_nonregular")
        if selected & absent:
            raise ValueError("historical_context_both_present_and_absent")
        if _receipt(archive) != archive_receipt:
            raise ValueError("historical_archive_changed_during_selection")
        partial.rename(safe_archive)
        record = {"version": 1, "archive": _receipt(safe_archive),
                  "source_archive": archive_receipt,
                  "source_manifest": _receipt(manifest_path) if manifest_path else None,
                  "test_paths": ["/" + p for p in explicit], "files": records,
                  "historically_absent_paths": ["/" + p for p in sorted(absent)],
                  "excluded": excluded, "needs_manual_review": bool(excluded),
                  "selection": "All regular explicit test files, conventional test filenames, and files under test/tests/fixtures/__tests__/__fixtures__/testdata components; blocked dependency/private directories excluded.",
                  "total_bytes": spent, "subject_executed": False}
        _write_new(output / "manifest.json", record)
        return {**record, "manifest": _receipt(output / "manifest.json")}
    except BaseException as exc:
        if partial.exists():
            partial.unlink()
        _write_new(output / "failure.json", {"error_type": type(exc).__name__, "error": str(exc)[:1000],
                                             "source_archive": archive_receipt, "subject_executed": False})
        raise


def patch_added_paths(patch):
    """Read Git new-file headers; reject unusual paths rather than guess cleanup."""
    added = []
    for section in re.split(r"(?m)^diff --git ", Path(patch).read_text())[1:]:
        header = re.split(r"(?m)^@@|^GIT binary patch$|^Binary files ", section, maxsplit=1)[0]
        if not re.search(r"(?m)^new file mode [0-7]+$", header):
            continue
        matches = re.findall(r"(?m)^\+\+\+ (.+)$", header)
        if len(matches) == 1:
            value = matches[0]
        elif not matches and ("GIT binary patch" in section or "Binary files " in section):
            names = shlex.split(header.splitlines()[0])
            if len(names) != 2 or not names[0].startswith("a/") or names[0][2:] != names[1][2:]:
                raise ValueError("ambiguous_added_binary_patch_path")
            value = names[1]
        else:
            raise ValueError("added_patch_path_missing_or_ambiguous")
        if value.startswith('"'):
            value = ast.literal_eval(value)
            if any(ord(char) >= 128 for char in value):
                raise ValueError("quoted_nonascii_git_path_requires_review")
        if not value.startswith("b/"):
            raise ValueError("added_patch_path_not_repository_relative")
        name = _name(value[2:], repository_relative=True)
        if _blocked(name):
            raise ValueError("patch_addition_in_dependency_or_private_path")
        added.append(name[4:])
    if len(added) != len(set(added)):
        raise ValueError("duplicate_added_patch_path")
    return added


def _checked(runtime, command, label):
    result = runtime.exec(command, label, timeout=180)
    if result.get("transport_error") or result.get("timed_out") or result.get("returncode") != 0:
        raise RuntimeError("context_repair_control_failed:" + label)
    return result


_PATH_OPERATIONS = r'''
import hashlib,json,os,stat,sys
with open(sys.argv[1]) as f:r=json.load(f)
action=r['action']; processed=changed=0
for item in r['files']:
    path=item['subject_path']; parts=path.split('/')[1:]
    if len(parts)<2 or parts[0] not in ('app','tmp') or any(p in ('','.','..') for p in parts):
        raise ValueError('unsafe_subject_path')
    current=''
    for part in parts[:-1]:
        current+='/'+part
        if os.path.lexists(current):
            mode=os.lstat(current).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise ValueError('non_directory_or_symlink_parent:'+current)
    exists=os.path.lexists(path)
    mode=os.lstat(path).st_mode if exists else None
    if action=='remove':
        if exists:
            if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                raise ValueError('refusing_nonfile_removal:'+path)
            os.unlink(path)
            changed+=1
    elif action=='preflight':
        if exists and not stat.S_ISREG(mode):
            raise ValueError('nonregular_restore_target:'+path)
    elif action=='verify':
        if not exists or not stat.S_ISREG(mode):
            raise ValueError('restored_context_file_missing:'+path)
        digest=hashlib.sha256()
        with open(path,'rb') as f:
            for block in iter(lambda:f.read(1048576),b''):digest.update(block)
        if digest.hexdigest()!=item['sha256'] or os.stat(path).st_size!=item['bytes']:
            raise ValueError('restored_context_hash_mismatch:'+path)
    else:raise ValueError('unknown_path_operation')
    processed+=1
print(json.dumps({'action':action,'files_processed':processed,'files_removed':changed}))
'''


def _path_operation(runtime, action, rows, label):
    # File payloads keep every shell argument comfortably below Linux's per-
    # argument limit even for repositories containing many thousands of tests.
    payload = runtime.output / "context_repair_inputs" / (label + ".json")
    _write_new(payload, {"action": action, "files": rows})
    destination = runtime.scratch + "/" + label + ".json"
    runtime.copy_to(payload, destination)
    result = _checked(runtime, "python3 -c " + shlex.quote(_PATH_OPERATIONS)
                      + " " + shlex.quote(destination), label)
    return {**result, "context_operation_payload": _receipt(payload)}


def _remove_files(runtime, paths, label):
    rows = [{"subject_path": "/" + _name(path)} for path in sorted(set(paths))]
    return _path_operation(runtime, "remove", rows, label) if rows else None


def restore_test_context(runtime, context, *, added_paths=()):
    """Restore a locally created safe archive after P, retaining exact receipts.

    ``added_paths`` are repository-relative new-file paths in P. New test files
    absent at the historical boundary are removed; historical deleted test
    paths remain absent. No recursive deletion or Git clean is performed.
    """
    _verify_receipt(context["manifest"])
    archive = _verify_receipt(context["archive"])
    frozen = _read(context["manifest"]["path"])
    if {k: v for k, v in context.items() if k != "manifest"} != frozen:
        raise ValueError("test_context_manifest_changed")
    present = {row["archive_path"] for row in context["files"]}
    remove = set(context.get("historically_absent_paths", []))
    remove.update("/" + _name(path, repository_relative=True) for path in added_paths
                  if is_test_context_path(path, context["test_paths"], repository_relative=True)
                  and _name(path, repository_relative=True) not in present)
    if {p.lstrip("/") for p in remove} & present:
        raise ValueError("test_context_restore_remove_overlap")
    removal = _remove_files(runtime, remove, "remove_nonhistorical_test_context")
    preflight = _path_operation(runtime, "preflight",
        [{"subject_path": row["subject_path"]} for row in context["files"]],
        "preflight_historical_test_context")
    destination = runtime.scratch + "/historical_test_context.tar.gz"
    runtime.copy_to(archive, destination)
    restoration = _checked(runtime, "tar -xzf " + shlex.quote(destination)
                           + " -C / --no-same-owner --same-permissions --unlink-first",
                           "restore_historical_test_context")
    verification = _path_operation(runtime, "verify",
        [{key: row[key] for key in ("subject_path", "sha256", "bytes")} for row in context["files"]],
        "verify_historical_test_context")
    return {"context_manifest": context["manifest"], "restored_files": context["files"],
            "removed_paths": sorted(remove), "removal": removal, "preflight": preflight,
            "restoration": restoration, "verification": verification,
            "baseline_dependencies_recursively_cleaned": False}


def _copy_bundle(source, destination):
    destination.mkdir(parents=True, exist_ok=False)
    result = []
    for name in ("sources.tar.gz", "manifest.json", "implementation.patch", "receipt.json"):
        item = source / name
        if item.is_symlink() or not item.is_file():
            raise ValueError("source_bundle_missing_or_nonregular:" + name)
        shutil.copyfile(item, destination / name)
        result.append({"source": _receipt(item), "copy": _receipt(destination / name)})
    return result


def recover_final_context(c, out=None, *, run=RUN, container_factory=None, activate=True):
    """Run only a corrected final phase from the saved original-test checkpoint.

    This function is opt-in execution, not a dry run. The historical trajectory
    and historical test-only rerun are inherited unchanged. A successful test
    *execution* may have a nonzero test verdict; timeout/transport/setup failures
    prevent activation. All failures retain their new logs and the old pointer.
    """
    from .experiment import collect_observation_files, activate_generated_runtime
    if container_factory is None:
        from .runtime import Container
        container_factory = Container
    run = Path(run).resolve()
    case = run / "runs" / c["id"]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", c["id"]):
        raise ValueError("invalid_case_id")
    pointer_path = case / "active_replay.json"
    pointer_bytes = pointer_path.read_bytes()
    pointer = json.loads(pointer_bytes)
    previous = Path(pointer["directory"]).resolve(strict=True)
    if previous.parent != case or previous.is_symlink():
        raise ValueError("active_replay_outside_case")
    _verify_receipt(pointer["summary"], within=case)
    old = _read(previous / "summary.json")
    snapshot = _read(previous / "test_snapshot.json")
    _verify_receipt(old["test_snapshot"], within=case)
    selection_path = case / "localization/selection.json"
    primary = dict(_read(selection_path)["primary"])
    primary["test_paths"], addendum = test_paths_with_addendum(case, primary["test_paths"])
    review = _read(case / "localization/command_review.json")
    if (review.get("approved_for_isolated_replay") is not True
            or review.get("selection_sha256") != _sha(selection_path)):
        raise ValueError("selection_lacks_matching_command_review")
    command = review.get("test_command", primary["test_command"]).strip()
    workdir = review.get("test_workdir", snapshot.get("working_directory", "/app"))
    observation_paths = review.get("observation_paths", snapshot.get("observation_paths", []))
    if command != snapshot["command"] or command != old["historical_test_only"]["command"]:
        raise ValueError("historical_command_changed")
    if workdir != snapshot.get("working_directory", "/app"):
        raise ValueError("historical_working_directory_changed")
    checkpoint = old["original_context_checkpoint"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", checkpoint["image_id"]):
        raise ValueError("original_context_image_not_immutable")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", c["base_commit"]):
        raise ValueError("base_commit_not_full_hash")
    patch = run / "inputs" / c["id"] / "model.patch"
    additions = patch_added_paths(patch)
    cleanup = classify_historical_additions(snapshot.get("historical_production_additions_to_remove", []),
                                            test_paths=primary["test_paths"])
    source_paths = ["/" + _name(path, repository_relative=True) for path in primary["source_paths"]]
    output = Path(out) if out is not None else Path("replay_context_repair01")
    output = (case / output if not output.is_absolute() else output).absolute()
    if output.parent.resolve() != case or output.exists() or output.is_symlink():
        raise FileExistsError("Recovery requires a new immediate child of the case directory")
    output.mkdir()
    checkpoint_file = previous / "context/checkpoints/original_test_context/result.json"
    checkpoint_receipt = _receipt(checkpoint_file) if checkpoint_file.is_file() else _receipt(previous / "summary.json")
    inherited = {"original_replay": str(previous), "checkpoint_receipt": checkpoint_receipt,
                 "image_id": checkpoint["image_id"], "head": checkpoint["head"],
                 "reason": "Final-phase replay machinery repair: retain the full historical test/fixture context while transplanting submitted production P. No test repair or masking-factor edit.",
                 "inherited_original_command_and_historical_rerun": True}
    _write_new(output / "recovery.json", inherited)
    _write_new(output / "historical/records.json", [])
    _write_new(output / "historical/inherited.json", {"executed_here": False, **inherited})
    try:
        copied = _copy_bundle(previous / "historical_sources", output / "historical_sources")
        new_snapshot = copy.deepcopy(snapshot)
        new_snapshot["files"] = []
        new_snapshot["test_context_addendum"] = addendum
        for i, item in enumerate(snapshot["files"]):
            source = _verify_receipt(item, within=case)
            destination = output / "test_snapshot" / f"{i:02}_{source.name}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            new_snapshot["files"].append({"subject_path": item["subject_path"], **_receipt(destination)})
        with container_factory(checkpoint["image_id"], output / "final", checkpoint["head"]) as runtime:
            inventory = _checked(runtime,
                "git -c safe.directory=/app ls-files --others --exclude-standard -z", "checkpoint_untracked_inventory")
            untracked = [p for p in inventory["stdout"].split("\0") if p]
            context_extras = ["/" + _name(p, repository_relative=True) for p in untracked
                              if is_test_context_path(p, primary["test_paths"], repository_relative=True)]
            deleted = _checked(runtime, "git -c safe.directory=/app diff --name-only --diff-filter=D "
                               + shlex.quote(c["base_commit"]) + " -z --", "historical_deleted_paths")
            absent = ["/" + _name(p, repository_relative=True) for p in deleted["stdout"].split("\0")
                      if p and is_test_context_path(p, primary["test_paths"], repository_relative=True)]
            # The old cleanup list was computed against the original image's
            # baseline inventory. Its production paths are known historical
            # additions, not dependency files that happened to be untracked.
            known_historical_sources = ["/" + _name(p, repository_relative=True)
                                        for p in cleanup["production_to_remove"]]
            # Public patch additions can also be documentation/data files. Freeze
            # every colliding regular file before clearing it, not just source
            # extensions. patch_added_paths rejects private/dependency paths.
            colliding_patch_paths = ["/" + _name(p, repository_relative=True)
                                     for p in additions if p in untracked]
            extras = sorted(set(context_extras + primary["test_paths"] + source_paths
                                + known_historical_sources + colliding_patch_paths))
            complete = runtime.snapshot("before_context_repair", extra_paths=extras)
            _copy_bundle(Path(complete["archive"]).parent, output / "historical_sources_supplement01")
            context = build_test_context_archive(complete["archive"], output / "test_context",
                test_paths=primary["test_paths"], manifest_path=complete["manifest"], absent_paths=absent)
            copied_tests = {item["subject_path"] for item in new_snapshot["files"]}
            for path in primary["test_paths"]:
                if path not in copied_tests:
                    destination = output / "test_snapshot" / f"{len(new_snapshot['files']):02}_{Path(path).name}"
                    runtime.copy_from(path, destination)
                    new_snapshot["files"].append({"subject_path": path, **_receipt(destination)})
            present = {row["archive_path"] for row in context["files"]}
            # Files inherited from the checkpoint but excluded from public archives
            # cannot safely be destroyed to make an added patch file fit.
            manifest = _read(complete["manifest"])
            known = {_name(row["path"]) for row in manifest["files"] if row.get("kind") == "file"}
            unknown_collisions = [p for p in additions if p in untracked
                                  and _name(p, repository_relative=True) not in known]
            if unknown_collisions:
                _write_new(output / "ambiguous_patch_collisions.json", {"paths": unknown_collisions})
                raise ValueError("patch_additions_overlap_unarchived_checkpoint_files")
            for item in new_snapshot["files"]:
                rows = [row for row in context["files"] if row["subject_path"] == item["subject_path"]]
                if len(rows) != 1 or rows[0]["sha256"] != item["sha256"]:
                    raise ValueError("checkpoint_selected_test_differs_from_original_snapshot")
            _checked(runtime, "git -c safe.directory=/app reset --hard " + shlex.quote(c["base_commit"]),
                     "restore_base_source")
            _remove_files(runtime, ["/" + _name(p, repository_relative=True)
                                   for p in cleanup["production_to_remove"]],
                          "remove_historical_production_additions")
            _remove_files(runtime, ["/" + _name(p, repository_relative=True) for p in additions],
                          "clear_patch_additions")
            patch_result = runtime.apply_patch(patch, "submitted_patch")
            restoration = restore_test_context(runtime, context, added_paths=additions)
            activation = activate_generated_runtime(runtime, case)
            final_snapshot = runtime.snapshot("before_final_test", extra_paths=sorted(set(
                [row["subject_path"] for row in context["files"]] + primary["test_paths"] + source_paths)))
            _copy_bundle(Path(final_snapshot["archive"]).parent, output / "final_sources")
            final_checkpoint = runtime.checkpoint("final_test_context")
            final = runtime.exec(command, "final_test_only", timeout=180, workdir=workdir)
            collect_observation_files(runtime, observation_paths, output / "final_observation_files", final)
            if final.get("transport_error") or final.get("timed_out"):
                raise RuntimeError("corrected_final_test_runtime_failure")
            if any(row.get("error") for row in final.get("observation_files", [])):
                raise RuntimeError("corrected_final_test_observation_file_missing")
        repair = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                  "inherited": inherited, "copied_original_historical_bundle": copied,
                  "fresh_historical_snapshot": complete, "context": context,
                  "checkpoint_untracked_inventory": inventory, "historical_deleted_paths": deleted,
                  "cleanup_classification": cleanup, "submitted_patch": _receipt(patch),
                  "test_context_addendum": addendum,
                  "patch_additions": additions, "patch_application": patch_result,
                  "generated_runtime_activation": activation,
                  "restoration": restoration, "final_snapshot": final_snapshot,
                  "historical_subject_reexecuted": False, "final_subject_executed": True,
                  "baseline_untracked_dependencies_preserved_by_no_recursive_clean": True,
                  "needs_manual_review": True, "scientific_masking_verdict": None}
        _write_new(output / "context_repair.json", repair)
        new_snapshot.update(historical_production_additions_to_remove=cleanup["production_to_remove"],
                            context_repair=_receipt(output / "context_repair.json"))
        _write_new(output / "test_snapshot.json", new_snapshot)
        result = {**copy.deepcopy(old), "status": "replayed_pending_fidelity_review",
                  "final_test_only": final, "final_context_checkpoint": final_checkpoint,
                  "inherited_restoration": inherited, "test_snapshot": _receipt(output / "test_snapshot.json"),
                  "context_repair": _receipt(output / "context_repair.json"),
                  "generated_runtime_activation": activation,
                  "qualification": "The historical command and rerun are inherited unchanged; the corrected final phase preserves historical test context. Fidelity and eligibility require review; no masking verdict is made."}
        _write_new(output / "summary.json", result)
        if activate:
            if pointer_path.read_bytes() != pointer_bytes:
                raise RuntimeError("active_replay_changed_during_context_recovery")
            temporary = case / (".active_replay_" + uuid.uuid4().hex + ".json")
            _write_new(temporary, {"directory": str(output), "summary": _receipt(output / "summary.json")})
            os.replace(temporary, pointer_path)
        return {"id": c["id"], "status": result["status"], "directory": str(output),
                "activated": activate, "historical_context_files": len(present),
                "final_returncode": final.get("returncode"), "scientific_masking_verdict": None}
    except BaseException as exc:
        _write_new(output / "failure.json", {"id": c["id"], "status": "context_repair_failed",
                    "error_type": type(exc).__name__, "error": str(exc)[:1000],
                    "active_pointer_unchanged": pointer_path.read_bytes() == pointer_bytes})
        raise
