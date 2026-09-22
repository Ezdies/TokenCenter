UV ?= uv
COMPOSE ?= docker compose
SPIKE_COMPOSE = infrastructure/docker/compose.spike.yml

.PHONY: bootstrap check format lint test typecheck frontend-check up smoke ps logs down clean spike-up spike-test spike-down

bootstrap:
	$(UV) sync --all-packages --all-groups

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

lint:
	$(UV) run ruff format --check .
	$(UV) run ruff check .

test:
	$(UV) run pytest

typecheck:
	$(UV) run mypy

frontend-check:
	cd apps/dashboard-angular && npm run format:check
	cd apps/dashboard-angular && npm test -- --watch=false
	cd apps/dashboard-angular && npm run build

check: lint typecheck test frontend-check

up:
	$(COMPOSE) up -d --build --wait

smoke:
	./scripts/smoke-stack.sh

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=200

down:
	$(COMPOSE) down --remove-orphans

clean:
	$(COMPOSE) down --remove-orphans --volumes

spike-up:
	$(COMPOSE) -f $(SPIKE_COMPOSE) up -d --wait

spike-test:
	./scripts/smoke-litellm-plugin.sh

spike-down:
	$(COMPOSE) -f $(SPIKE_COMPOSE) down --remove-orphans
