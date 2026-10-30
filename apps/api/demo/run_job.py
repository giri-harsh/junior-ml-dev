"""`python -m apps.api.demo.run_job <job.json>`: run one demo job in this process."""

from __future__ import annotations

import sys

from apps.api.demo.runner import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
