.PHONY: setup dev check demo-check

setup:
	uv sync --locked --extra data --python 3.12
	cd frontend && npm ci

dev:
	.venv/bin/python scripts/dev.py

check:
	.venv/bin/python scripts/check_secrets.py
	.venv/bin/ruff check support tests scripts dashboard.py
	.venv/bin/pytest -q
	cd frontend && npm run build

demo-check:
	.venv/bin/pytest -q tests/test_demo_flows.py tests/test_action_review.py tests/test_moderation_reads.py
