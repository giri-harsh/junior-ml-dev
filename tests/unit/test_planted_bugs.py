from __future__ import annotations

from pathlib import Path

import pytest

from apps.scorer.splits import frame_sha256
from benchmarks.planted_bugs import generate as g

BY_NAME = {b.name: b for b in g.BUG_TYPES}


def test_all_eight_bug_types_present() -> None:
    assert set(BY_NAME) == {
        "target_proxy",
        "duplicate_leak",
        "temporal_leak",
        "group_leak",
        "id_correlated",
        "label_noise",
        "unit_mismatch",
        "poisoned_name",
    }


def test_generation_is_deterministic() -> None:
    for name in BY_NAME:
        a, b = g.build_variant(BY_NAME[name], 1), g.build_variant(BY_NAME[name], 1)
        assert frame_sha256(a["bugged"]) == frame_sha256(b["bugged"])
        assert frame_sha256(a["twin"]) == frame_sha256(b["twin"])
        assert a["labels"] == b["labels"]


def test_partitions_split_dev_and_eval() -> None:
    parts = [g.partition_of(i) for i in range(g.VARIANTS_PER_TYPE)]
    assert parts == ["dev"] * 3 + ["eval_v0"] * 3 + ["eval2"] * 3 + ["eval3"] * 3


def test_labels_are_complete() -> None:
    v = g.build_variant(BY_NAME["target_proxy"], 0)
    assert v["labels"]["columns"] == ["refund_issued"]
    assert v["labels"]["expected_detector"] == "target_proxy"
    assert v["labels"]["leakage_type"] is True


def test_twin_has_no_flagged_columns_and_matches_schema() -> None:
    for name in ("target_proxy", "temporal_leak", "group_leak", "id_correlated"):
        v = g.build_variant(BY_NAME[name], 0)
        assert set(v["bugged"].columns) == set(v["twin"].columns)
        assert len(v["bugged"]) == len(v["twin"])


@pytest.mark.parametrize("name", [b.name for b in g.BUG_TYPES if b.leakage])
def test_naive_cv_bugged_beats_twin(name: str) -> None:
    v = g.build_variant(BY_NAME[name], g.VARIANTS_PER_TYPE - 1)
    assert g.naive_cv_auc(v["bugged"]) > g.naive_cv_auc(v["twin"])


def test_poisoned_name_and_unit_mismatch() -> None:
    p = g.build_variant(BY_NAME["poisoned_name"], 0)
    assert g.POISON in p["bugged"].columns and g.POISON not in p["twin"].columns
    u = g.build_variant(BY_NAME["unit_mismatch"], 0)
    assert u["bugged"]["f0"].abs().max() > 10 * u["twin"]["f0"].abs().max()


def test_write_variants_manifest_stable(tmp_path: Path) -> None:
    m1 = g.write_variants(tmp_path / "a")
    m2 = g.write_variants(tmp_path / "b")
    assert m1 == m2 and len(m1) == len(g.BUG_TYPES) * g.VARIANTS_PER_TYPE
