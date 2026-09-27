.PHONY: install install-dev fix check test run

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install -e '.[dev]'

fix:
	ruff check --fix src tests
	ruff format src tests

check:
	ruff check src tests
	ruff format --check src tests
	mypy src tests
	pytest

test:
	pytest

run:
	codex-free-worker stdio
