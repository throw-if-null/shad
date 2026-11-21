.PHONY: install test lint typecheck check coral-contract

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src/

typecheck:
	mypy src/

check: lint typecheck test

coral-contract:
	scripts/check-coral-contract.sh
