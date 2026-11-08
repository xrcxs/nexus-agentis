.PHONY: install dev-backend dev-frontend test test-backend test-frontend e2e lint typecheck eval docker-up

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -r backend/requirements.txt
	cd frontend && npm install

dev-backend:
	PYTHONPATH=. uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

test: test-backend

test-backend:
	PYTHONPATH=. $(PYTHON) -m unittest backend/tests/test_unit.py backend/tests/test_integration.py -v

test-frontend:
	cd frontend && npm run test

e2e:
	cd frontend && npx playwright test

lint:
	ruff check backend eval
	cd frontend && npm run lint

typecheck:
	mypy backend/models backend/services backend/graph backend/app
	cd frontend && npx tsc --noEmit

eval:
	PYTHONPATH=. $(PYTHON) eval/run_eval.py

docker-up:
	docker compose up --build
