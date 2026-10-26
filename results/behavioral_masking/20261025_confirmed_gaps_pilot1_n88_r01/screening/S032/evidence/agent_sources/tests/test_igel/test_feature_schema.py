"""Tests for persisted feature schema handling."""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from igel.feature_schema import (
    apply_feature_schema,
    build_feature_schema,
    FeatureSchemaError,
)


def _run_py(code, cwd):
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _write_workspace():
    tmp = Path(tempfile.mkdtemp())
    rng = np.random.RandomState(7)
    n = 40
    train = pd.DataFrame(
        {
            "a": np.arange(n, dtype=float),
            "b": rng.rand(n),
            "c": rng.rand(n),
            "const": np.ones(n),
            "a_dup": np.arange(n, dtype=float),
            "noise": rng.rand(n),
            "label": rng.randint(0, 2, size=n),
        }
    )
    train.to_csv(tmp / "train.csv", index=False)

    pred = pd.DataFrame(
        {
            "a_dup": np.arange(n, dtype=float),
            "b": rng.rand(n),
            "c": rng.rand(n),
            "const": np.ones(n),
            "noise": rng.rand(n),
            "extra": rng.rand(n),
        }
    )
    pred.to_csv(tmp / "pred.csv", index=False)

    eval_df = pd.DataFrame(
        {
            "a": np.arange(n, dtype=float),
            "b": rng.rand(n),
            "c": rng.rand(n),
            "const": np.ones(n),
            "a_dup": np.arange(n, dtype=float),
            "noise": rng.rand(n),
            "label": rng.randint(0, 2, size=n),
            "extra": rng.rand(n),
        }
    )
    eval_df.to_csv(tmp / "eval.csv", index=False)

    yaml_content = """
dataset:
    type: csv
    split:
        test_size: 0.25
        shuffle: false
    features:
        include: [a, b, c, const, a_dup]
        exclude: noise
        drop_constant: true
        drop_duplicate: true
    preprocess:
        missing_values: mean
model:
    type: classification
    algorithm: LogisticRegression
target:
    - label
"""
    (tmp / "igel.yaml").write_text(yaml_content)
    return tmp


def test_build_and_apply_schema():
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0],
            "a2": [1.0, 2.0, 3.0],
            "b": [1, 1, 1],
            "c": [4.0, 5.0, 6.0],
            "target": [0, 1, 0],
        }
    )
    schema, selected = build_feature_schema(
        df,
        ["target"],
        {
            "include": ["c", "a", "a2", "b"],
            "drop_constant": True,
            "drop_duplicate": True,
        },
    )
    assert selected == ["c", "a"]
    assert schema["input_features"] == ["c", "a"]
    assert schema["dropped_features"] == {
        "excluded": [],
        "constant": ["b"],
        "duplicate": ["a2"],
    }
    assert schema["duplicate_feature_aliases"] == {"a": ["a2"]}

    new = pd.DataFrame(
        {"a2": [10.0, 20.0, 30.0], "c": [1.0, 2.0, 3.0], "extra": [9, 9, 9]}
    )
    out, selected = apply_feature_schema(new, schema, [])
    assert selected == ["c", "a2"]
    assert list(out.columns) == ["c", "a2"]

    with pytest.raises(
        FeatureSchemaError, match="missing required selected feature"
    ):
        apply_feature_schema(pd.DataFrame({"c": [1.0, 2.0]}), schema, [])

    conflicting = pd.DataFrame(
        {"a": [1.0, 2.0, 3.0], "a2": [9.0, 9.0, 9.0], "c": [1.0, 2.0, 3.0]}
    )
    with pytest.raises(FeatureSchemaError, match="conflicting columns"):
        apply_feature_schema(conflicting, schema, [])


def test_fit_persists_schema_evaluate_and_predict_apply_it():
    tmp = _write_workspace()
    code = r'''
import json
import pandas as pd
from igel import Igel

Igel(cmd="fit", data_path="train.csv", yaml_path="igel.yaml")
with open("model_results/description.json") as f:
    d = json.load(f)
assert d["input_features"] == ["a", "b", "c"], d
assert d["dropped_features"] == {
    "excluded": ["noise"],
    "constant": ["const"],
    "duplicate": ["a_dup"],
}, d
assert d["duplicate_feature_aliases"] == {"a": ["a_dup"]}, d
assert "feature_schema_path" in d
assert __import__("os").path.exists("model_results/feature_schema.joblib")

Igel(cmd="evaluate", data_path="eval.csv")
Igel(cmd="predict", data_path="pred.csv")
preds = pd.read_csv("model_results/predictions.csv")
assert len(preds) == 40
print("E2E_OK")
'''
    res = _run_py(code, tmp)
    assert "E2E_OK" in res.stdout, res.stdout + res.stderr


def test_missing_and_conflicting_features_raise():
    tmp = _write_workspace()
    code = r'''
import pandas as pd
from igel import Igel
Igel(cmd="fit", data_path="train.csv", yaml_path="igel.yaml")

pd.DataFrame({"b": [1.0, 2.0], "c": [3.0, 4.0]}).to_csv(
    "missing.csv", index=False
)
try:
    Igel(cmd="predict", data_path="missing.csv")
except Exception as e:
    assert "a" in str(e), str(e)
else:
    raise AssertionError("missing feature did not raise")

pd.DataFrame({
    "a": [1.0, 2.0, 3.0],
    "a_dup": [9.0, 9.0, 9.0],
    "b": [1.0, 2.0, 3.0],
    "c": [1.0, 2.0, 3.0],
}).to_csv("conflict.csv", index=False)
try:
    Igel(cmd="predict", data_path="conflict.csv")
except Exception as e:
    assert "a" in str(e) and "a_dup" in str(e), str(e)
else:
    raise AssertionError("conflicting columns did not raise")
print("ERRORS_OK")
'''
    res = _run_py(code, tmp)
    assert "ERRORS_OK" in res.stdout, res.stdout + res.stderr


def test_invalid_feature_configs_raise():
    tmp = _write_workspace()
    code = r'''
from igel import Igel
cases = [
    {"include": ["unknown", "a"]},
    {"exclude": ["unknown"]},
    {"include": ["a", "label"]},
    {"include": ["a", "a"]},
    {"exclude": ["noise", "noise"]},
    {"include": ["a", "b"], "exclude": ["b"]},
    {"include": []},
    {"include": ""},
    {"drop_constant": True, "include": ["const"]},
]
yaml_template = (
    "dataset:\n"
    "    type: csv\n"
    "    features:\n"
    "{lines}\n"
    "    preprocess:\n"
    "        missing_values: mean\n"
    "model:\n"
    "    type: classification\n"
    "    algorithm: LogisticRegression\n"
    "target:\n"
    "    - label\n"
)
for features in cases:
    lines = "\n".join(f"        {k}: {v!r}" for k, v in features.items())
    with open("bad.yaml", "w") as f:
        f.write(yaml_template.format(lines=lines))
    try:
        Igel(cmd="fit", data_path="train.csv", yaml_path="bad.yaml")
    except Exception:
        pass
    else:
        raise AssertionError(f"invalid config did not raise: {features}")
print("INVALID_OK")
'''
    res = _run_py(code, tmp)
    assert "INVALID_OK" in res.stdout, res.stdout + res.stderr


def test_predict_endpoint_returns_400_on_schema_failure():
    tmp = _write_workspace()
    code = r'''
import os
from igel import Igel
Igel(cmd="fit", data_path="train.csv", yaml_path="igel.yaml")
os.environ["IGEL_MODEL_RESULTS_PATH"] = "model_results"
from fastapi.testclient import TestClient
from igel.servers.fastapi_server import app
client = TestClient(app)
r = client.post("/predict", json={"b": [1.0, 2.0], "c": [3.0, 4.0]})
assert r.status_code == 400, r.text
assert "a" in r.json()["detail"], r.text
print("SERVER_OK")
'''
    res = _run_py(code, tmp)
    assert "SERVER_OK" in res.stdout, res.stdout + res.stderr


def test_multi_target_fit_predict():
    tmp = Path(tempfile.mkdtemp())
    rng = np.random.RandomState(11)
    n = 40
    train = pd.DataFrame(
        {
            "a": np.arange(n, dtype=float),
            "b": rng.rand(n),
            "a_dup": np.arange(n, dtype=float),
            "y1": rng.randint(0, 2, size=n),
            "y2": rng.randint(0, 2, size=n),
        }
    )
    train.to_csv(tmp / "train.csv", index=False)
    pred = pd.DataFrame(
        {
            "a_dup": np.arange(n, dtype=float),
            "b": rng.rand(n),
            "extra": rng.rand(n),
        }
    )
    pred.to_csv(tmp / "pred.csv", index=False)
    (tmp / "igel.yaml").write_text(
        """
dataset:
    type: csv
    split:
        test_size: 0.25
        shuffle: false
    features:
        include: [a, b, a_dup]
        drop_duplicate: true
    preprocess:
        missing_values: mean
model:
    type: classification
    algorithm: LogisticRegression
target:
    - y1
    - y2
"""
    )
    code = r"""
import json
import pandas as pd
from igel import Igel
Igel(cmd="fit", data_path="train.csv", yaml_path="igel.yaml")
with open("model_results/description.json") as f:
    d = json.load(f)
assert d["input_features"] == ["a", "b"], d
assert d["duplicate_feature_aliases"] == {"a": ["a_dup"]}, d
Igel(cmd="predict", data_path="pred.csv")
preds = pd.read_csv("model_results/predictions.csv")
assert list(preds.columns) == ["y1", "y2"], preds.columns
print("MULTI_OK")
"""
    res = _run_py(code, tmp)
    assert "MULTI_OK" in res.stdout, res.stdout + res.stderr


def test_clustering_fit_evaluate_predict():
    tmp = Path(tempfile.mkdtemp())
    rng = np.random.RandomState(13)
    n = 50
    train = pd.DataFrame(
        {
            "x": rng.rand(n),
            "y": rng.rand(n),
            "x_dup": rng.rand(n),
            "const": np.ones(n),
            "noise": rng.rand(n),
        }
    )
    train["x_dup"] = train["x"]
    train.to_csv(tmp / "train.csv", index=False)
    eval_df = pd.DataFrame(
        {
            "x_dup": rng.rand(n),
            "y": rng.rand(n),
            "noise": rng.rand(n),
            "extra": rng.rand(n),
        }
    )
    eval_df.to_csv(tmp / "eval.csv", index=False)
    eval_df.to_csv(tmp / "pred.csv", index=False)
    (tmp / "igel.yaml").write_text(
        """
dataset:
    type: csv
    features:
        include: [x, y, x_dup, const]
        exclude: noise
        drop_constant: true
        drop_duplicate: true
    preprocess:
        missing_values: mean
model:
    type: clustering
    algorithm: KMeans
"""
    )
    code = r"""
import json
from igel import Igel
Igel(cmd="fit", data_path="train.csv", yaml_path="igel.yaml")
with open("model_results/description.json") as f:
    d = json.load(f)
assert d["input_features"] == ["x", "y"], d
Igel(cmd="evaluate", data_path="eval.csv")
Igel(cmd="predict", data_path="pred.csv")
print("CLUSTER_OK")
"""
    res = _run_py(code, tmp)
    assert "CLUSTER_OK" in res.stdout, res.stdout + res.stderr


def test_export_derives_input_width_from_description():
    tmp = _write_workspace()
    code = r'''
import igel.igel as igel_mod
from igel import Igel

Igel(cmd="fit", data_path="train.csv", yaml_path="igel.yaml")

captured = {}
class FakeOnnx:
    def SerializeToString(self):
        return b"fake"

def fake_convert(model, initial_types=None):
    captured["initial_types"] = initial_types
    return FakeOnnx()

igel_mod.convert_sklearn = fake_convert
Igel(cmd="export", model_path="model_results/model.joblib")
shape = captured["initial_types"][0][1].shape
assert shape[1] == 3, shape
print("EXPORT_OK")
'''
    res = _run_py(code, tmp)
    assert "EXPORT_OK" in res.stdout, res.stdout + res.stderr
