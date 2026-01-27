VENV=.venv
PY=$(VENV)/bin/python
PORT=8000

.PHONY: run kill dev shadow-on shadow-off

run:
	@if [ ! -d "$(VENV)" ]; then python3 -m venv $(VENV); fi
	@$(PY) -m pip install --upgrade pip
	@$(PY) -m pip install -r sentinel_x/requirements.txt
	@$(PY) run_sentinel_x.py

kill:
	@echo "Killing processes on port $(PORT)..."
	@lsof -ti tcp:$(PORT) | xargs kill -9 2>/dev/null || true

dev: kill
	@echo "Starting Aegis Alpha in DEV mode..."
	@$(PY) api/main.py

shadow-on:
	@curl -s -X POST http://localhost:$(PORT)/shadow/start | jq .

shadow-off:
	@curl -s -X POST http://localhost:$(PORT)/shadow/stop | jq .
