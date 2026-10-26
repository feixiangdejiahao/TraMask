"""Executable negative controls for the bounded construction prototype."""
from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from prototypes.owner_prefix_slice import propose_candidate, slice_prefix


@pytest.mark.parametrize("owner,item,value,build,mutate,publish,read,retire,probe", [
    ("owner", "item", "value", "Build", "Add", "Accept", "Counter", "Release", "Inspect"),
    ("garden", "plant", "height", "Sprout", "Water", "Plant", "Measure", "Pot", "Count"),
])
def test_resource_operations_survive_generic_renaming(owner, item, value, build, mutate, publish, read, retire, probe):
    prefix = f'''check(t, {owner}.{probe}(0))
{item} := {owner}.{build}()
check(t, {item}.{mutate}(1))
check(t, {owner}.{publish}({item}))
{value} := {item}.{read}()
check(t, {item}.{retire}())'''
    result = slice_prefix(prefix, value + "+2")
    assert result["status"] == "proposed"
    assert f"{owner}.{probe}" not in result["prefix"]
    for invocation in (build, mutate, publish, read, retire):
        assert invocation in result["prefix"]
    assert result["dependency_complete"] is False
    assert result["removed"][0]["reason"] == "preconstruction_owner_effect_unknown"
    for receipt in result["retained"] + result["removed"]:
        assert prefix.encode()[receipt["start_byte"]:receipt["end_byte"]].decode() == receipt["code"]


def test_distinct_objects_and_nested_calls_and_argument_dependencies():
    prefix = '''other := stranger.Build()
check(t, other.Touch())
item := owner.Build()
key := []byte("x")
check(t, item.Store(key))
check(t, transmit(owner, item))
value := inspect(item)
check(t, item.Retire())'''
    result = slice_prefix(prefix, "value+1")
    assert "stranger" not in result["prefix"]
    assert "other.Touch" not in result["prefix"]
    assert "key :=" in result["prefix"]
    assert "item.Store" in result["prefix"]
    assert "transmit(owner, item)" in result["prefix"]
    assert "item.Retire" in result["prefix"]


def test_reaching_definitions_do_not_use_later_assignment():
    result = slice_prefix('''amount := 3
item := owner.Build()
item.Store(amount)
amount = 8
value := item.Read()''', "value")
    assert "amount := 3" in result["prefix"]
    assert "amount = 8" not in result["prefix"]


def test_alias_operation_retained():
    result = slice_prefix('''owner.Probe()
item := owner.Build()
alias := item
alias.Store(7)
value := item.Read()''', "value")
    assert "alias := item" in result["prefix"]
    assert "alias.Store(7)" in result["prefix"]


def test_reverse_alias_and_tuple_error_check_retained():
    result = slice_prefix('''owner.Probe()
item := owner.Build()
alias := item
item.Store(7)
value, err := alias.Read()
check(err)''', "value")
    assert "item.Store(7)" in result["prefix"]
    assert "check(err)" in result["prefix"]


@pytest.mark.parametrize("statement", [
    "if ready { owner.Touch() }", "for i := 0; i < 2; i++ { owner.Touch() }",
    "defer owner.Finish()", "go owner.Touch()", "*alias = 4",
])
def test_unsupported_state_is_unknown_not_empty_slice(statement):
    result = slice_prefix(statement + "\nitem := owner.Build()\nvalue := item.Read()", "value")
    assert result["status"] == "unknown"
    assert result["prefix"] is None
    assert result["unknown"]


def test_extra_candidate_retains_parent_and_original_assertion_edits():
    candidate = {"id": "parent", "edits": [
        {"role": "state_prefix", "after": "owner.Probe()\nitem := owner.Build()\nvalue := item.Read()", "before": "", "span": {"start_byte": 7, "end_byte": 7}},
        {"role": "binding", "after": "value+1", "before": "8", "span": {"start_byte": 9, "end_byte": 10}},
        {"role": "semantic_expected", "after": "8", "before": "9"},
    ], "equivalence_key": "original"}
    before = deepcopy(candidate)
    result = propose_candidate(candidate)
    assert candidate == before
    assert result["candidate"]["id"] != candidate["id"]
    assert result["candidate"]["edits"][1:] == candidate["edits"][1:]
    assert "equivalence_key" not in result["candidate"]
    assert result["candidate"]["prefix_slice"]["equivalence_claim"] is False


TOY = '''package main
type Workshop struct { ready bool }
type Piece struct { value int; active bool }
func (w *Workshop) Arm() error { w.ready = true; return nil }
func (w *Workshop) Probe() error { if !w.ready { panic("probe requires ready") }; return nil }
func (w *Workshop) Make() *Piece { if !w.ready { panic("missing prerequisite") }; return &Piece{active:true} }
func (p *Piece) Add(n int) error { if !p.active { panic("inactive") }; p.value += n; return nil }
func (w *Workshop) Commit(p *Piece) error { p.value *= 2; return nil }
func (p *Piece) Read() int { return p.value }
func (p *Piece) Retire() error { p.active = false; return nil }
func check(err error) { if err != nil { panic(err) } }
'''


def test_real_prerequisite_before_child_creation_is_retained_and_executes(tmp_path):
    if shutil.which("go") is None:
        pytest.skip("Go compiler is required for executable control")
    prefix = '''check(owner.Probe())
check(owner.Arm())
piece := owner.Make()
check(piece.Add(3))
check(owner.Commit(piece))
value := piece.Read()
check(piece.Retire())'''
    source = Source("toy.go", TOY, "go")
    result = slice_prefix(prefix, "value+1", sources=[source])
    assert "owner.Probe" not in result["prefix"]
    assert "owner.Arm" in result["prefix"]
    armed = next(s for s in result["retained"] if "owner.Arm" in s["code"])
    assert "possible_callee_receiver_write" in armed["reasons"]
    assert armed["write_evidence"]["Arm"][0]["path"] == "toy.go"
    target = tmp_path / "main.go"
    target.write_text(TOY + "func main(){ owner := &Workshop{}\n" + result["prefix"] + '\nif value+1 != 7 { panic("bad value") }; if piece.active { panic("not retired") }\n}')
    environment = {**os.environ, "GO111MODULE": "off", "GOWORK": "off", "GOCACHE": str(tmp_path / "go-cache")}
    run = subprocess.run(["go", "run", str(target)], env=environment, text=True, capture_output=True, timeout=90)
    assert run.returncode == 0, run.stderr
    # Omitting this state operation really breaks the construction.  This is
    # not merely a test mirroring the chosen syntactic retention rule.
    target.write_text(target.read_text().replace("check(owner.Arm())", ""))
    broken = subprocess.run(["go", "run", str(target)], env=environment, text=True, capture_output=True, timeout=30)
    assert broken.returncode != 0
    assert "missing prerequisite" in broken.stderr


def test_missing_method_body_does_not_claim_removed_prerequisite_irrelevant():
    result = slice_prefix("check(owner.Arm())\npiece := owner.Make()\nvalue := piece.Read()", "value")
    assert result["removed"][0]["reason"] == "preconstruction_owner_effect_unknown"
    assert any(x.get("statement") == 0 for x in result["unknown"])
    assert result["dependency_complete"] is False
