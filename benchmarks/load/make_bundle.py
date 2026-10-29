"""Train a small model on synthetic data and package it; prints the bundle directory as JSON.

Used by the load workflow so the predict-service container has something real to serve.
Writes load_example.json (3 rows) into the working directory.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="load-"))
    (root / "data").mkdir()
    os.environ["DATA_TOOLS_ROOTS"] = str(root / "data")
    os.environ["EXPERIMENTS_DIR"] = str(root / "exp")
    os.environ["DEPLOY_DIR"] = str(root / "deploy")
    from mcp_servers.deploy import service as dp
    from mcp_servers.experiments import service as ex

    rng = np.random.default_rng(0)
    n = 5000
    df = pd.DataFrame({f"f{i}": rng.normal(size=n) for i in range(8)})
    df["seg"] = rng.choice(["a", "b", "c"], n)
    df["y"] = (df.f0 + 0.5 * df.f1 + rng.normal(scale=0.5, size=n) > 0).astype(int)
    p = root / "data" / "load.parquet"
    df.to_parquet(p)
    req = ex.TrainRequest(
        data_path=str(p), target="y", task_type="binary", metric="roc_auc",
        run_id="load", family="rf", selection="holdout",
    )  # fmt: skip
    rec = ex.train_model(req)
    res = dp.package_model(dp.PackageRequest(run_id="load", model_id=rec.model_id))
    shutil.copyfile(Path(res.bundle_dir) / "example_request.json", "load_example.json")
    print(json.dumps({"bundle_dir": res.bundle_dir}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
