import os

# Spans go to stderr by default; keep test output quiet unless a test installs its own exporter.
os.environ.setdefault("JMD_TRACE", "off")
