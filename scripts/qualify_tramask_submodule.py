"""Read-only qualification of an unchanged uninitialized documentation gitlink."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_pilot.runtime import Container
from tramask_rerun.study import RUN, write_new, now
from tramask_rerun.reserved import load_cases

INSPECT = '''import json,os,stat,subprocess
p="/app/site/themes/hello-friend"
info=os.lstat(p)
def git(*args):
    r=subprocess.run(["git","-C","/app",*args],capture_output=True)
    return {"returncode":r.returncode,"stdout":r.stdout.decode(),"stderr":r.stderr.decode()}
print(json.dumps({"path":p,"directory":stat.S_ISDIR(info.st_mode),"symlink":stat.S_ISLNK(info.st_mode),
"entries":sorted(os.listdir(p)),"git_marker_present":os.path.lexists(p+"/.git"),
"head_entry":git("ls-tree","HEAD","--","site/themes/hello-friend"),
"index_entry":git("ls-files","--stage","--","site/themes/hello-friend"),
"status":git("submodule","status","--","site/themes/hello-friend")}))
'''

if __name__ == "__main__":
    case = next(c for c in load_cases() if c["id"] == "HS005")
    directory = RUN / "runs/HS005"
    replay = directory / "submission_replay_v01"
    summary = read(replay / "summary.json")
    validation = read(replay / "validation/report.json")
    expected = validation["unverified"]
    if (validation["mismatches"] or len(expected) != 1 or expected[0]["path"] != "site/themes/hello-friend"
            or expected[0]["reason"] != "submodule_worktree_not_validated"
            or not validation["submitted_commit_tree_matches"] or not validation["index_tree_matches_submitted_commit"]):
        raise ValueError("Not the uniquely identified gitlink validation limitation")
    out = directory / "submodule_validation_v02"
    if out.exists():
        raise FileExistsError("Preserve existing submodule validation attempt")
    out.mkdir()
    snapshots = {}
    for name, image, head in [("initial", case["image"], case["base_commit"]),
                               ("terminal", summary["checkpoint"]["image_id"], summary["checkpoint"]["head"])]:
        with Container(image, out / name, head, **case["resources"]) as runtime:
            result = runtime._control(["python3", "-I", "-c", INSPECT], timeout=30, check=False)
            (out / (name + ".stdout.bin")).write_bytes(result.stdout)
            (out / (name + ".stderr.bin")).write_bytes(result.stderr)
            if result.returncode:
                raise ValueError("Read-only submodule inspection failed")
            snapshots[name] = json.loads(result.stdout)
    oid = expected[0]["expected"]["oid"]
    for value in snapshots.values():
        assert value["directory"] and not value["symlink"] and value["entries"] == [] and not value["git_marker_present"]
        assert value["head_entry"]["returncode"] == value["index_entry"]["returncode"] == value["status"]["returncode"] == 0
        assert value["head_entry"]["stdout"].startswith("160000 commit " + oid + "\t")
        assert value["index_entry"]["stdout"].startswith("160000 " + oid + " 0\t")
        assert value["status"]["stdout"].startswith("-" + oid + " ")
    assert snapshots["initial"] == snapshots["terminal"]
    report = {"created_at": now(), "case_id": "HS005", "submission_filesystem_state_status": "matched_with_explicit_gitlink_qualification",
        "previous_validation": receipt(replay / "validation/report.json"), "checkpoint": summary["checkpoint"],
        "snapshots": snapshots, "all_regular_tracked_files_matched_previously": validation["matched_existing_files"],
        "gitlink_qualification": "Same expected committed/index gitlink OID and same empty uninitialized directory in initial image and terminal replay. No file contents or submodule checkout were invented.",
        "subject_files_or_real_index_patched": False, "all_original_actions_replayed": summary["actions_executed"],
        "scope_limit": "No original external untracked filesystem manifest; live-process equivalence is not asserted.",
        "raw_receipts": [receipt(out / name) for name in ("initial.stdout.bin", "initial.stderr.bin", "terminal.stdout.bin", "terminal.stderr.bin")]}
    write_new(out / "report.json", report)
    pointer = {"image_id": summary["checkpoint"]["image_id"], "head": summary["checkpoint"]["head"],
               "summary": receipt(replay / "summary.json"), "validation": receipt(out / "report.json"),
               "state_validation_passed": True, "requires_manual_qualification": True,
               "scope": "Terminal submitted tracked state plus unchanged uninitialized gitlink explicitly qualified; original replay/code unchanged."}
    write_new(directory / "active_submission_state.json", pointer)
    print(json.dumps({"case_id": "HS005", "status": report["submission_filesystem_state_status"], "checkpoint_unchanged": True}))
