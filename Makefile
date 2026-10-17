PY ?= python
.PHONY: install dev backend portal frontend test test-e2e reset fmt

install:
	$(PY) -m pip install -r backend/requirements.txt
	@if [ -f frontend/package.json ]; then cd frontend && npm install; fi

dev:
	bash scripts/dev.sh

backend:
	cd backend && $(PY) -m uvicorn app.main:app --reload --port 8000

portal:
	cd portal && $(PY) -m uvicorn main:app --reload --port 8100

frontend:
	cd frontend && npm run dev

test:
	cd backend && $(PY) -m pytest -q -m "not portal"

test-e2e:
	bash scripts/test_e2e.sh

reset:
	curl -s -X POST http://localhost:8000/demo/reset -H "Content-Type: application/json" -d '{"create_task": false, "mode": "fixture"}'

fmt:
	cd backend && $(PY) -m ruff format app tests || true
