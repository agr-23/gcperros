# Atajos del proyecto. `make` a secas lista lo que hay.
#
# Todo apunta a `.venv/bin/python` en lugar de a `python` a secas, asi que
# funciona con el entorno activado o sin activar: no hay que acordarse.

VENV := .venv
PY   := $(VENV)/bin/python
BIN  := $(VENV)/bin

.DEFAULT_GOAL := help
.PHONY: help setup hooks check lint format types test cov size demo clean

help: ## Lista los comandos disponibles
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[1m%-9s\033[0m %s\n", $$1, $$2}'

setup: ## Crea el entorno, instala dependencias y engancha pre-commit
	python3 -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -e ".[dev]"
	$(PY) -m pre_commit install --install-hooks
	@echo
	@echo "Listo. A partir de ahora, y sin que tengas que acordarte:"
	@echo "  commit  -> formato, secretos, gitmoji y convencion del mensaje"
	@echo "  push    -> limite de 250 deltas"
	@echo
	@echo "Lo lento sigue siendo manual: make check"

hooks: ## Reinstala los ganchos (necesario si se anadio uno nuevo)
	$(PY) -m pre_commit install --install-hooks

check: lint types test size ## Todo lo que la CI puede comprobar en local

lint: ## Errores, imports, nombres, seguridad y docstrings
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format: ## Formatea y arregla lo que se pueda arreglar solo
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

types: ## Tipos en modo estricto
	$(PY) -m mypy

test: ## La suite completa
	$(PY) -m pytest -q

cov: ## La suite con el umbral de cobertura de la CI
	$(PY) -m pytest -q --cov=gcperros --cov-fail-under=90

size: ## Deltas del cambio frente a origin/main
	$(PY) scripts/tamano_pr.py

demo: ## Genera un partido y lo pasa por frontera, calidad y trazabilidad
	$(BIN)/gcperros-generate-match --seed 20260826 --out partido.jsonl
	$(BIN)/gcperros-validate --stream match --in partido.jsonl --strict >/dev/null
	$(BIN)/gcperros-quality --stream match --in partido.jsonl --strict >/dev/null
	$(BIN)/gcperros-trace --in partido.jsonl --indicator total_xg --scope HOME

clean: ## Borra artefactos de herramientas y ficheros generados
	rm -rf .mypy_cache .pytest_cache .ruff_cache .coverage htmlcov
	rm -f *.jsonl calidad-*.json
