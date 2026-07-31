.PHONY: install lint test build deploy clean layer

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------
PYTHON := python
PIP := pip
SAM := sam
ENVIRONMENT ?= dev
REGION ?= us-east-1

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

install:
	$(PIP) install -r requirements-dev.txt

lint:
	ruff check shared/ agents/ workflow-starter/
	ruff format --check shared/ agents/ workflow-starter/
	mypy shared/ --ignore-missing-imports

format:
	ruff check --fix shared/ agents/ workflow-starter/
	ruff format shared/ agents/ workflow-starter/

test:
	pytest tests/ -v --cov=shared --cov=agents --cov=workflow-starter --cov-report=term-missing

# ---------------------------------------------------------------------------
# Build & Deploy
# ---------------------------------------------------------------------------

layer:
	@echo "Building shared layer..."
	@if exist shared-layer rmdir /s /q shared-layer
	@mkdir shared-layer\python\shared
	@copy shared\*.py shared-layer\python\shared\
	@echo "Layer built at shared-layer/"

build: layer
	$(SAM) build --template-file infrastructure/template.yaml

deploy: build
	$(SAM) deploy \
		--template-file infrastructure/template.yaml \
		--stack-name dark-factory-$(ENVIRONMENT) \
		--capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
		--region $(REGION) \
		--parameter-overrides \
			Environment=$(ENVIRONMENT) \
		--resolve-s3 \
		--no-confirm-changeset

validate:
	$(SAM) validate --template-file infrastructure/template.yaml

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

clean:
	@if exist shared-layer rmdir /s /q shared-layer
	@if exist .aws-sam rmdir /s /q .aws-sam
	@if exist .pytest_cache rmdir /s /q .pytest_cache
	@if exist htmlcov rmdir /s /q htmlcov
