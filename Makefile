# HHgoa4 fraud-investigation agent
# Real commands only -- every target maps to a script that actually exists in this repo.

.PHONY: install load run-one run-all validate test ui clean

install:
	pip install -r requirements.txt

# Loads transactions.csv / identity.csv / closed_cases_history.csv / case_pack.csv from
# ./data into TigerGraph. Requires .env (copy .env.example) and a live Savanna/CE
# workspace -- see src/graph/load.py.
load:
	python -m src.graph.load --data-dir ./data

# One case against the live graph. Override with: make run-one CASE=HHG-003
CASE ?= HHG-017
run-one:
	python -m src.agent.run --case $(CASE) --out cases/

# All 20 cases from data/case_pack.csv, in opened_at order, against the live graph.
run-all:
	python -m src.agent.run --all --out cases/

validate:
	python -m src.answer.validator cases/

test:
	python -m pytest tests/ -q

ui:
	cd ui && npm install && npm run dev

clean:
	rm -rf cases/*.json
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	find . -name ".pytest_cache" -type d -prune -exec rm -rf {} +
