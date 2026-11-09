"""Demo sample preparation: frame shaping errors, the size cap, the fetch wrapper (with a fake
OpenML), partial offline builds and the command-line entry point. Offline: no network."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from apps.api.demo import prepare
from apps.api.demo.samples import BY_KEY, Sample
from tests.demo.helpers import make_raw_samples

METRICS = """# Verified metrics

## Headline arm (unseen)

| Arm | Normalized score [95% CI] | Pass vs linear | Source |
|---|---|---|---|
| SCRIPTED planner (no LLM) | 0.424 [0.1, 0.9] | 3/10 | [`a.json`](../benchmarks/results/a.json) |
"""


def test_shape_frame_requires_the_target_after_renaming() -> None:
    with pytest.raises(ValueError, match="diabetes: target column 'diabetes' missing"):
        prepare.shape_frame(pd.DataFrame({"a": [1, 2]}), BY_KEY["diabetes"])


def test_shape_frame_refuses_a_binary_sample_without_a_positive_label() -> None:
    s = Sample("badbin", "t", 1, "y", "binary", "roc_auc", "b")
    with pytest.raises(ValueError, match="binary sample needs binary_positive"):
        prepare.shape_frame(pd.DataFrame({"y": ["a", "b"]}), s)


def test_shape_frame_binarises_the_label_and_flattens_categoricals() -> None:
    raw = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0],
            "c": pd.Categorical(["u", "v", "u"]),
            "class": pd.Categorical(["bad", "good", "bad"]),
        }
    )
    out = prepare.shape_frame(raw, BY_KEY["credit-g"])
    assert out["bad_credit"].tolist() == [1, 0, 1]
    assert out["c"].dtype == object or str(out["c"].dtype).startswith("str")
    assert out["c"].tolist() == ["u", "v", "u"]
    assert "class" not in out.columns
    assert raw["c"].dtype.name == "category"  # the input frame is not mutated


def test_fetch_asks_openml_for_the_sample_id_with_the_arff_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sklearn.datasets

    seen: dict[str, Any] = {}
    frame = pd.DataFrame({"a": [1]})

    def fake_fetch_openml(**kw: Any) -> SimpleNamespace:
        seen.update(kw)
        return SimpleNamespace(frame=frame)

    monkeypatch.setattr(sklearn.datasets, "fetch_openml", fake_fetch_openml)
    got = prepare._fetch(BY_KEY["diabetes"], tmp_path / "cache")
    assert got is frame
    assert seen == {
        "data_id": 37,
        "as_frame": True,
        "parser": "liac-arff",
        "data_home": str(tmp_path / "cache"),
    }


def test_write_sample_records_hash_and_size(tmp_path: Path) -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "diabetes": [0, 1, 0]})
    entry = prepare.write_sample(df, BY_KEY["diabetes"], tmp_path)
    csv = tmp_path / "diabetes.csv"
    assert entry == {
        "key": "diabetes",
        "rows": 3,
        "cols": 2,
        "bytes": csv.stat().st_size,
        "sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
        "openml_id": 37,
    }


def test_write_sample_deletes_a_file_over_the_size_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prepare, "MAX_SAMPLE_BYTES", 10)
    df = pd.DataFrame({"a": range(50), "diabetes": [0] * 50})
    with pytest.raises(ValueError, match=r"diabetes: \d+ bytes exceeds the 10 byte cap"):
        prepare.write_sample(df, BY_KEY["diabetes"], tmp_path)
    assert not (tmp_path / "diabetes.csv").exists()


def test_prepare_from_dir_skips_missing_samples_and_writes_a_manifest(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    make_raw_samples(raw)
    (raw / "wine-quality.csv").unlink()
    entries = prepare.prepare_samples(tmp_path / "out", from_dir=raw)
    assert [e["key"] for e in entries] == ["diabetes", "credit-g"]
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert [e["key"] for e in manifest["samples"]] == ["diabetes", "credit-g"]
    assert not (tmp_path / "out" / "wine-quality.csv").exists()
    shaped = pd.read_csv(tmp_path / "out" / "diabetes.csv")
    assert set(shaped["diabetes"]) == {0, 1}  # label turned into 0/1


def test_prepare_without_from_dir_fetches_into_a_cache_next_to_the_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw"
    make_raw_samples(raw)
    asked: list[tuple[str, Path]] = []

    def fake_fetch(s: Sample, cache: Path) -> pd.DataFrame:
        asked.append((s.key, cache))
        return pd.read_csv(raw / f"{s.key}.csv")

    monkeypatch.setattr(prepare, "_fetch", fake_fetch)
    data_dir = tmp_path / "data" / "samples"
    entries = prepare.prepare_samples(data_dir)
    assert [k for k, _ in asked] == ["diabetes", "credit-g", "wine-quality"]
    assert {c for _, c in asked} == {tmp_path / "data" / "_openml_cache"}
    assert [e["key"] for e in entries] == [k for k, _ in asked]
    custom = tmp_path / "mycache"
    prepare.prepare_samples(data_dir, cache=custom)
    assert asked[-1][1] == custom


def test_main_builds_samples_then_the_landing_page_and_removes_the_fetch_cache(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = tmp_path / "raw"
    make_raw_samples(raw)
    metrics = tmp_path / "METRICS.md"
    metrics.write_text(METRICS, encoding="utf-8")
    data_dir = tmp_path / "d" / "samples"
    cache = data_dir.parent / "_openml_cache"
    cache.mkdir(parents=True)
    (cache / "junk.bin").write_bytes(b"x")
    argv = [
        "--data-dir", str(data_dir), "--site-dir", str(tmp_path / "site"),
        "--metrics", str(metrics), "--from-dir", str(raw),
    ]  # fmt: skip
    assert prepare.main(argv) == 0
    out = capsys.readouterr().out
    assert "sample diabetes: 300x3" in out
    assert "sample wine-quality: 300x3" in out
    assert (tmp_path / "site" / "index.html").is_file()
    assert f"landing page: {tmp_path / 'site' / 'index.html'}" in out
    assert not cache.exists()


def test_main_fails_when_no_sample_could_be_prepared(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    argv = ["--data-dir", str(tmp_path / "d"), "--from-dir", str(empty)]
    assert prepare.main(argv) == 1
    captured = capsys.readouterr()
    assert "no samples prepared" in captured.err
    assert "landing page" not in captured.out


def test_main_skip_fetch_renders_only_the_landing_page(tmp_path: Path) -> None:
    metrics = tmp_path / "METRICS.md"
    metrics.write_text(METRICS, encoding="utf-8")
    argv = [
        "--skip-fetch", "--data-dir", str(tmp_path / "d" / "samples"),
        "--site-dir", str(tmp_path / "site"), "--metrics", str(metrics),
    ]  # fmt: skip
    assert prepare.main(argv) == 0
    assert (tmp_path / "site" / "index.html").is_file()
    assert not (tmp_path / "d" / "samples").exists()  # nothing fetched or written
