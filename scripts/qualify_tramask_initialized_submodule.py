"""Compare an initialized gitlink's commit and full literal tree without edits."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tramask_pilot.corpus import read, receipt
from tramask_pilot.runtime import Container
from tramask_rerun.study import RUN, write_new, now
from tramask_rerun.reserved import load_cases

INSPECT = '''import hashlib,json,os,stat,subprocess
root="/app/site/themes/hello-friend"
def git(*args):
    r=subprocess.run(["git","-C",root,*args],capture_output=True)
    return {"returncode":r.returncode,"stdout":r.stdout.decode(),"stderr":r.stderr.decode()}
rows=[]
for base,dirs,files in os.walk(root,followlinks=False):
    for name in sorted(dirs+files):
        p=os.path.join(base,name);info=os.lstat(p)
        row={"path":os.path.relpath(p,root),"permissions":stat.S_IMODE(info.st_mode)}
        if stat.S_ISLNK(info.st_mode):row.update(kind="symlink",target=os.readlink(p))
        elif stat.S_ISDIR(info.st_mode):row.update(kind="directory")
        elif stat.S_ISREG(info.st_mode):
            raw=open(p,"rb").read();row.update(kind="file",bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        else:raise ValueError("unexpected special file")
        rows.append(row)
print(json.dumps({"head":git("rev-parse","HEAD"),"index":git("write-tree"),"head_tree":git("rev-parse","HEAD^{tree}"),
"status":git("status","--porcelain=v1","--untracked-files=all"),"tree":sorted(rows,key=lambda r:r["path"])}))
'''

if __name__ == "__main__":
    case = next(c for c in load_cases() if c["id"] == "HS005")
    directory = RUN / "runs/HS005"
    replay = directory / "submission_replay_v01"
    summary, validation = read(replay / "summary.json"), read(replay / "validation/report.json")
    assert not validation["mismatches"] and len(validation["unverified"]) == 1
    unverified = validation["unverified"][0]
    assert unverified["path"] == "site/themes/hello-friend" and unverified["reason"] == "submodule_worktree_not_validated"
    expected = unverified["expected"]["oid"]
    out = directory / "submodule_validation_v03"
    out.mkdir(exist_ok=False)
    snapshots = {}
    for name, image, head in [("initial", case["image"], case["base_commit"]),
                               ("terminal", summary["checkpoint"]["image_id"], summary["checkpoint"]["head"])]:
        with Container(image, out / name, head, **case["resources"]) as runtime:
            result = runtime._control(["python3", "-I", "-c", INSPECT], timeout=60, check=False)
            (out / (name + ".stdout.bin")).write_bytes(result.stdout)
            (out / (name + ".stderr.bin")).write_bytes(result.stderr)
            assert result.returncode == 0
            snapshots[name] = json.loads(result.stdout)
    for value in snapshots.values():
        assert all(value[k]["returncode"] == 0 for k in ("head", "index", "head_tree", "status"))
        assert value["head"]["stdout"].strip() == expected
        assert value["index"]["stdout"] == value["head_tree"]["stdout"]
        assert value["status"]["stdout"] == ""
    assert snapshots["initial"]["tree"] == snapshots["terminal"]["tree"]
    assert validation["submitted_commit_tree_matches"] and validation["index_tree_matches_submitted_commit"]
    report = {"created_at": now(), "case_id": "HS005", "submission_filesystem_state_status": "matched_with_initialized_gitlink_qualification",
        "previous_validation": receipt(replay / "validation/report.json"), "checkpoint": summary["checkpoint"],
        "expected_gitlink_commit": expected, "snapshots": snapshots,
        "all_regular_tracked_files_matched_previously": validation["matched_existing_files"],
        "gitlink_qualification": "Both images contain the expected initialized submodule commit, clean literal worktree/index and exactly identical complete recursive file bytes, paths, permissions and symlink targets.",
        "prior_attempt": "v02 incorrectly assumed uninitialized state; assertion stopped without activating checkpoint. Its raw snapshots are retained and motivated this initialized-state verification.",
        "subject_files_or_real_index_patched": False, "subject_commands_replayed_again": False,
        "scope_limit": "Does not establish historical untracked global filesystem or live-process identity.",
        "raw_receipts": [receipt(out / n) for n in ("initial.stdout.bin", "initial.stderr.bin", "terminal.stdout.bin", "terminal.stderr.bin")]}
    write_new(out / "report.json", report)
    write_new(directory / "active_submission_state.json", {"image_id": summary["checkpoint"]["image_id"], "head": summary["checkpoint"]["head"],
        "summary": receipt(replay / "summary.json"), "validation": receipt(out / "report.json"), "state_validation_passed": True,
        "requires_manual_qualification": True, "scope": "Submitted tracked state and unchanged initialized gitlink qualified. Runtime/environment risks retained separately."})
    print(json.dumps({"case_id": "HS005", "state_validation_passed": True, "submodule_paths_compared": len(snapshots["terminal"]["tree"])}))
