.PHONY: help dev up down reset seed init status logs \
       tunnel tunnel-login tunnel-status \
       test lint format shell migrate makemigrations \
       build-widget dev-widget

# Default target
help: ## Show this help message
	@echo "Showdesk Development Commands"
	@echo "=============================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Dev orchestration (delegates to dev.py)
# ---------------------------------------------------------------------------

dev: ## Full bootstrap: infra → init → app → migrate → seed
	python3 dev.py

up: ## Start services (skip init if already done)
	python3 dev.py up

down: ## Stop all services
	python3 dev.py down

reset: ## Nuke volumes and re-bootstrap everything
	python3 dev.py reset

seed: ## Seed database with demo data
	python3 dev.py seed

init: ## Run init steps only
	python3 dev.py init

status: ## Show service status
	python3 dev.py status

logs: ## Tail all service logs
	python3 dev.py logs

# ---------------------------------------------------------------------------
# Cloudflare tunnel
# ---------------------------------------------------------------------------

tunnel: ## Start a quick tunnel (*.trycloudflare.com)
	python3 dev.py tunnel

tunnel-named: ## Start a named tunnel (requires tunnel-login)
	python3 dev.py tunnel --named

tunnel-login: ## Authenticate cloudflared for Showdesk
	python3 dev.py tunnel-login

tunnel-status: ## Show tunnel info
	python3 dev.py tunnel-status

# ---------------------------------------------------------------------------
# Django (quick access — requires running stack)
# ---------------------------------------------------------------------------

migrate: ## Run database migrations
	docker compose exec backend python manage.py migrate

makemigrations: ## Create new database migrations
	docker compose exec backend python manage.py makemigrations

shell: ## Open Django shell
	docker compose exec backend python manage.py shell_plus

createsuperuser: ## Create a Django superuser
	docker compose exec backend python manage.py createsuperuser

# ---------------------------------------------------------------------------
# Testing & Quality
# ---------------------------------------------------------------------------

test: ## Run backend tests
	docker compose exec backend python -m pytest -v

test-cov: ## Run backend tests with coverage
	docker compose exec backend python -m pytest --cov=apps --cov-report=term-missing

lint: ## Run linters (ruff)
	docker compose exec backend ruff check .

format: ## Format code (ruff)
	docker compose exec backend ruff format .

# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

build-widget: ## Build the embeddable widget
	cd widget && npm run build

dev-widget: ## Start widget dev mode with watch
	cd widget && npm run dev
