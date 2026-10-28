from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.api.main import app
from apps.api.routes import datasets
from apps.api.store import LocalObjectStore
from datastory.pii import scan_pii
from datastory.quality import quality_report


def _clean(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "age": rng.integers(18, 90, n),
            "city": rng.choice(["New York", "Boston", "Chicago"], n),
            "income": rng.normal(50, 10, n).round(2),
        }
    )


def test_clean_frame_scores_high_with_no_deductions() -> None:
    r = quality_report(_clean())
    assert r.score >= 99 and r.deductions == []
    assert set(r.subscores) == {
        "completeness",
        "uniqueness",
        "validity",
        "consistency",
        "timeliness",
        "leakage_risk",
    }


def test_each_injected_defect_causes_a_deduction() -> None:
    base = _clean()
    base_score = quality_report(base).score
    cases = {
        "completeness": base.assign(
            income=base["income"].where(np.arange(len(base)) % 4 != 0, np.nan)
        ),
        "uniqueness": pd.concat([base, base.iloc[:100]], ignore_index=True),
        "validity": base.assign(age=base["age"].where(np.arange(len(base)) % 10 != 0, -5)),
        "consistency": base.assign(city=base["city"].replace({"New York": "NY"})),
    }
    cases["consistency"].loc[:50, "city"] = "New York"
    for dim, df in cases.items():
        r = quality_report(df)
        assert any(d.dimension == dim for d in r.deductions), dim
        assert r.subscores[dim] < 100 and r.score < base_score, dim


def test_case_and_whitespace_variants_flagged() -> None:
    df = _clean()
    df.loc[:30, "city"] = " boston "
    r = quality_report(df)
    assert any(d.dimension == "consistency" and d.columns == ["city"] for d in r.deductions)


def test_numeric_as_text_and_future_dates() -> None:
    df = _clean()
    df["amount"] = [str(i) for i in range(len(df))]
    df.loc[0, "amount"] = "n/a"
    df["when"] = pd.to_datetime("2025-06-01") + pd.to_timedelta(np.arange(len(df)), unit="D")
    r = quality_report(df, as_of=date(2025, 8, 1))
    dims = {d.dimension for d in r.deductions}
    assert {"validity", "timeliness"} <= dims


def test_timeliness_skipped_without_as_of() -> None:
    df = _clean().assign(when=pd.Timestamp("2000-01-01"))
    assert quality_report(df).subscores["timeliness"] == 100.0


@given(st.lists(st.floats(allow_nan=True, allow_infinity=True, width=32), min_size=1, max_size=40))
@settings(max_examples=40, deadline=None)
def test_property_scorecard_never_crashes_and_stays_bounded(vals: list[float]) -> None:
    df = pd.DataFrame({"price": vals, "label": ["a"] * len(vals)})
    r = quality_report(df)
    assert 0 <= r.score <= 100 and all(0 <= v <= 100 for v in r.subscores.values())


def test_pii_scan_flags_only_columns() -> None:
    df = pd.DataFrame({"mail": [f"u{i}@example.com" for i in range(20)], "note": ["hello"] * 20})
    assert scan_pii(df) == {"email": ["mail"]}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    datasets.set_store(LocalObjectStore(tmp_path / "store"))
    yield TestClient(app)  # type: ignore[misc]
    datasets.set_store(None)


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def test_upload_profile_quality_roundtrip(client: TestClient) -> None:
    df = _clean()
    r = client.post("/v1/datasets", files={"file": ("d.csv", _csv_bytes(df))})
    assert r.status_code == 202
    did = r.json()["dataset_id"]
    st_ = client.get(f"/v1/datasets/{did}/status").json()
    assert st_["status"] == "ready" and st_["n_rows"] == len(df)
    prof = client.get(f"/v1/datasets/{did}/profile").json()
    assert prof["n_rows"] == len(df) and {c["name"] for c in prof["columns"]} == set(df.columns)
    q = client.get(f"/v1/datasets/{did}/quality").json()
    assert q["score"] >= 99


def test_upload_is_content_addressed(client: TestClient) -> None:
    body = _csv_bytes(_clean())
    a = client.post("/v1/datasets", files={"file": ("a.csv", body)}).json()
    b = client.post("/v1/datasets", files={"file": ("b.csv", body)}).json()
    assert a["dataset_id"] == b["dataset_id"]


def test_upload_rejections(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.post("/v1/datasets", files={"file": ("x.exe", b"abc")}).status_code == 415
    assert client.post("/v1/datasets", files={"file": ("x.csv", b"")}).status_code == 422
    monkeypatch.setattr(datasets, "MAX_BYTES", 10)
    assert (
        client.post("/v1/datasets", files={"file": ("x.csv", b"a,b\n" + b"1,2\n" * 50)}).status_code
        == 413
    )


def test_unparsable_file_marks_failed(client: TestClient) -> None:
    did = client.post("/v1/datasets", files={"file": ("x.parquet", b"not parquet")}).json()[
        "dataset_id"
    ]
    assert client.get(f"/v1/datasets/{did}/status").json()["status"] == "failed"
    assert client.get(f"/v1/datasets/{did}/profile").status_code == 409


def test_unknown_and_malformed_ids_are_404(client: TestClient) -> None:
    assert client.get("/v1/datasets/0123456789abcdef/status").status_code == 404
    assert client.get("/v1/datasets/..%2Fetc/status").status_code == 404
    assert client.get("/v1/datasets/ZZZ/profile").status_code == 404


def test_quality_with_leakage_feeds_leakage_risk(client: TestClient) -> None:
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"x": rng.normal(size=500), "target": rng.integers(0, 2, 500)})
    df["leak"] = df["target"]
    did = client.post("/v1/datasets", files={"file": ("d.csv", _csv_bytes(df))}).json()[
        "dataset_id"
    ]
    q = client.get(
        f"/v1/datasets/{did}/quality", params={"target": "target", "with_leakage": "true"}
    )
    assert q.status_code == 200 and q.json()["subscores"]["leakage_risk"] < 100
    bad = client.get(f"/v1/datasets/{did}/quality", params={"with_leakage": "true"})
    assert bad.status_code == 422


def test_upload_file_buffer_not_trusted_for_path(client: TestClient) -> None:
    did = client.post(
        "/v1/datasets", files={"file": ("../../evil.csv", io.BytesIO(b"a\n1\n2\n3\n"))}
    ).json()["dataset_id"]
    assert ".." not in client.get(f"/v1/datasets/{did}/status").json()["filename"]
