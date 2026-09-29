import copy
import inspect

import pytest

from relation_search.semantic_selection import select


def corpus_and_candidates(language="python", name="value", number=4, count=24):
    if language == "python":
        code = f"def test_case():\n    {name} = source()\n    consume({name}, {number})\n"
        filename = "test_sample.py"
    elif language == "go":
        code = f"package sample\nfunc TestCase(t *testing.T) {{ {name}:=source(); consume({name}, {number}) }}"
        filename = "sample_test.go"
    else:
        code = f"test('case',()=>{{ const {name}=source(); consume({name}, {number}); }});"
        filename = "sample.test.ts"
    position = code.index(str(number), code.index("consume"))
    corpus = {"language": language, "sources": {filename: {"code": code}},
              "tests": {"seed": {"retrieval_rank": 3, "span": {"path": filename, "start_byte": 0, "end_byte": len(code)}}}}
    candidates = [{"id": f"candidate_{i:03d}", "operator": "numeric", "base_test_id": "seed",
                   "edits": [{"span": {"path": filename, "start_byte": position, "end_byte": position+len(str(number))},
                              "before": str(number), "after": str(100+i), "role": "input"}],
                   "relation": {}, "source_retrieval_rank": 3} for i in range(count)]
    return corpus, candidates


@pytest.mark.parametrize("language", ["python", "go", "typescript"])
def test_names_and_literal_values_do_not_define_edit_shape(language):
    first_corpus, first = corpus_and_candidates(language, "value", 4, 1)
    second_corpus, second = corpus_and_candidates(language, "renamed", 47, 1)
    second[0]["edits"][0]["after"] = "9876"
    a = select(first_corpus, first)["ranking"][0]
    b = select(second_corpus, second)["ranking"][0]
    assert a["normalization_status"] == b["normalization_status"] == "parsed"
    assert a["shape_id"] == b["shape_id"]
    assert a["content_sha256"] != b["content_sha256"]


def test_budget_zero_and_sixteen_keep_complete_ranking_and_do_not_mutate_inputs():
    corpus, candidates = corpus_and_candidates()
    original = copy.deepcopy((corpus, candidates))
    zero = select(corpus, candidates, budget=0)
    sixteen = select(corpus, candidates, budget=16)
    assert zero["selected"] == [] and len(zero["ranking"]) == 24
    assert len(sixteen["selected"]) == 16 and len(sixteen["unselected_ids"]) == 8
    assert [row["id"] for row in zero["ranking"]] == [row["id"] for row in sixteen["ranking"]]
    assert sum(row["selected"] for row in sixteen["ranking"]) == 16
    assert (corpus, candidates) == original


def test_first_shape_representatives_precede_same_shape_value_variants():
    corpus, candidates = corpus_and_candidates(count=8)
    different = copy.deepcopy(candidates[0])
    different["id"] = "expression_variant"
    different["edits"][0]["after"] = "source()"
    candidates.append(different)
    result = select(corpus, candidates, budget=2)
    assert result["shape_count"] == 2
    assert {row["variant_round"] for row in result["ranking"][:2]} == {0}
    assert result["ranking"][2]["variant_round"] == 1
    assert "expression_variant" in {row["id"] for row in result["selected"]}
    assert len({row["id"] for row in result["ranking"]}) == len(candidates)


def test_family_and_seed_fairness_are_independent_of_input_order():
    corpus, base = corpus_and_candidates(count=5)
    candidates = []
    for family in ("alpha", "beta", "gamma"):
        for seed_index in range(2):
            seed = f"seed_{seed_index}"
            corpus["tests"][seed] = {"retrieval_rank": seed_index}
            for candidate in base:
                row = copy.deepcopy(candidate)
                row.update(id=family+seed+row["id"], operator=family, base_test_id=seed,
                           source_retrieval_rank=seed_index)
                candidates.append(row)
    a = select(corpus, candidates, budget=16)
    b = select(corpus, list(reversed(candidates)), budget=16)
    assert a == b
    assert [row["family"] for row in a["ranking"][:6]] == ["alpha","beta","gamma"]*2
    assert [row["base_test_id"] for row in a["ranking"][:6]] == ["seed_0"]*3+["seed_1"]*3
    assert all(row["variant_round"] == 0 for row in a["ranking"][:6])
    assert a["ranking"][6]["variant_round"] == 1


def test_cache_and_evaluation_metadata_cannot_affect_selection():
    assert tuple(inspect.signature(select).parameters) == ("corpus", "candidates", "budget")
    corpus, candidates = corpus_and_candidates()
    annotated = copy.deepcopy(candidates)
    for index, candidate in enumerate(annotated):
        candidate["oracle_cache"] = {"hit": index % 2 == 0}
        candidate["evaluation"] = {"is_target": index == 23}
        candidate["runtime_outcome"] = "failed" if index == 23 else "passed"
    a = select(corpus, candidates)
    b = select(corpus, annotated)
    assert a["ranking"] == b["ranking"]
    assert [row["id"] for row in a["selected"]] == [row["id"] for row in b["selected"]]


def test_existing_profiles_roles_and_argument_slots_remain_distinguishable():
    corpus, candidates = corpus_and_candidates(count=1)
    base = candidates[0]
    profile = copy.deepcopy(base)
    profile.update(id="other_profile", relation={"profile": [-1, 0, 1]})
    role = copy.deepcopy(base)
    role["id"] = "other_role"
    role["edits"][0]["role"] = "binding"
    slot = copy.deepcopy(base)
    slot["id"] = "other_slot"
    code = corpus["sources"]["test_sample.py"]["code"]
    position = code.index("value",code.index("consume"))
    slot["edits"][0].update(before="value",after="100",span={"path":"test_sample.py","start_byte":position,"end_byte":position+5})
    result = select(corpus,[base,profile,role,slot])
    assert result["shape_count"] == 4


def test_identical_material_candidates_get_stable_tie_order_without_repetition():
    corpus, candidates = corpus_and_candidates(count=1)
    duplicate = copy.deepcopy(candidates[0]);duplicate["id"] = "second_identity"
    a = select(corpus,[duplicate,*candidates])
    b = select(corpus,[*candidates,duplicate])
    assert a == b
    assert [row["variant_round"] for row in a["ranking"]] == [0,1]


def test_import_alias_spelling_does_not_create_a_new_shape():
    corpus,candidates = corpus_and_candidates("typescript",count=1)
    first = candidates[0]
    first["edits"][0]["after"] = "newAlias()"
    first["imports"] = [{"name":"newAlias","module":"./helpers","imported_name":"construct"}]
    second = copy.deepcopy(first)
    second["id"] = "renamed_import"
    second["edits"][0]["after"] = "differentAlias()"
    second["imports"][0]["name"] = "differentAlias"
    result = select(corpus,[first,second])
    assert result["shape_count"] == 1


def test_invalid_span_is_explicit_and_does_not_disappear_from_ranking():
    corpus, candidates = corpus_and_candidates(count=2)
    candidates[1]["edits"][0]["before"] = "wrong"
    result = select(corpus,candidates)
    invalid = next(row for row in result["ranking"] if row["id"] == candidates[1]["id"])
    assert invalid["normalization_status"] == "invalid_or_overlapping_span"
    assert len(result["ranking"]) == len(result["selected"]) == 2


def test_empty_input_and_invalid_budget_and_duplicate_ids():
    corpus, candidates = corpus_and_candidates(count=1)
    assert select(corpus,[])['ranking'] == []
    with pytest.raises(ValueError):select(corpus,candidates,budget=-1)
    with pytest.raises(ValueError):select(corpus,candidates*2)
