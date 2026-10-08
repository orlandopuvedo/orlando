.PHONY: install install-browser dev backend frontend test build start migrate typecheck

PY=backend/.venv/bin/python

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm install

install-browser:
	cd backend && .venv/bin/pip install -r requirements-browser.txt && .venv/bin/playwright install chromium

migrate:
	cd backend && .venv/bin/alembic upgrade head

backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

dev:
	@echo "Run 'make backend' and 'make frontend' in two terminals, then open http://localhost:5173"

test:
	cd backend && .venv/bin/pytest -q

typecheck:
	cd frontend && npx tsc -b

build:
	cd frontend && npm run build

start: build
	cd backend && .venv/bin/uvicorn app.main:app --host $${APP_HOST:-127.0.0.1} --port $${APP_PORT:-8000}
