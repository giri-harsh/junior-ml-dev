from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.results_writer import Conditions, load_result, write_result


def test_result_is_stamped(tmp_path: Path) -> None:
    cond = Conditions(llm="mocked", sandbox="fake", n=3)
    p = write_result("demo", {"score": 0.5}, cond, command="python x.py", out_dir=tmp_path)
    rec = load_result(p)
    assert rec.command == "python x.py"
    assert rec.conditions.llm == "mocked" and rec.conditions.n == 3
    assert rec.git_sha and rec.date and rec.conditions.machine_id
    assert rec.results == {"score": 0.5}


def test_invalid_condition_value_rejected() -> None:
    with pytest.raises(ValueError):
        Conditions(llm="gpt", sandbox="fake", n=1)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["", "a/b", "..\\x"])
def test_path_like_name_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        write_result(name, {}, Conditions(llm="none", sandbox="none", n=0), out_dir=tmp_path)
