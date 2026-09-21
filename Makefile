# SILLAGE — команди розробки (Linux / macOS / Git Bash).
# На Windows у PowerShell користуйся .\scripts\dev.ps1 — там ті самі команди.

ifeq ($(OS),Windows_NT)
	PYTHON := .venv/Scripts/python.exe
else
	PYTHON := .venv/bin/python
endif

MANAGE := $(PYTHON) manage.py

.DEFAULT_GOAL := help
.PHONY: help run migrate makemigrations seed seed-fast render test lint format superuser \
        check check-prod collectstatic shell urls install

help:  ## показати цей список
	@echo ""
	@echo "SILLAGE — команди розробки"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""

run:  ## runserver на 127.0.0.1:8000
	$(MANAGE) runserver

migrate:  ## застосувати міграції
	$(MANAGE) migrate

makemigrations:  ## створити міграції
	$(MANAGE) makemigrations

seed:  ## migrate + каталог SILLAGE + фото товарів
	$(MANAGE) migrate
	$(MANAGE) seed_shop --flush
	$(MANAGE) load_product_photos

seed-fast:  ## каталог без рендеру зображень
	$(MANAGE) migrate
	$(MANAGE) seed_shop --flush --no-images

render:  ## лише рендер зображень (ARGS="--only=slug --force")
	$(MANAGE) render_product_images $(ARGS)

test:  ## прогнати тести
	$(MANAGE) test

lint:  ## ruff check + black --check
	$(PYTHON) -m ruff check .
	$(PYTHON) -m black --check .

format:  ## ruff --fix + black
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m black .

superuser:  ## створити адміністратора
	$(MANAGE) createsuperuser

check:  ## manage.py check
	$(MANAGE) check

check-prod:  ## check --deploy з prod-налаштуваннями
	$(MANAGE) check --deploy --settings=shop_project.settings.prod

collectstatic:  ## зібрати статику в staticfiles/
	$(MANAGE) collectstatic --noinput

shell:  ## shell_plus
	$(MANAGE) shell_plus

urls:  ## show_urls
	$(MANAGE) show_urls

install:  ## поставити залежності
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt
