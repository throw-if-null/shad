.PHONY: install test lint typecheck check

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src/

typecheck:
	mypy src/

check: lint typecheck test
