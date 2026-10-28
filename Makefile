# Thin wrapper; the logic lives in scripts/tasks.py so Windows works without make.
PY ?= python

.PHONY: up down test lint secrets hooks
up:
	$(PY) scripts/tasks.py up
down:
	$(PY) scripts/tasks.py down
test:
	$(PY) scripts/tasks.py test
lint:
	$(PY) scripts/tasks.py lint
secrets:
	$(PY) scripts/tasks.py secrets
hooks:
	$(PY) scripts/tasks.py hooks
