# Agent payments platform. Local loop on kind; production on EKS via Terraform + Argo CD.
SHELL := /bin/bash
NS    := payments
KPS_VERSION    ?= 92.3.0
ARGOCD_VERSION ?= 10.10.2

.PHONY: help venv test lint keys image local-up local-secrets local-deploy local-down port-forward loadgen chaos \
        grafana aws-init aws-plan aws-up aws-kubeconfig argocd aws-down

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

# ---------- develop ----------
venv: ## Create .venv with dev dependencies
	python3.12 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt

lint: ## ruff
	.venv/bin/ruff check .

test: ## Unit + API tests (SQLite). Set TEST_DATABASE_URL=postgresql+psycopg://... for race tests
	.venv/bin/pytest -q

keys: ## Create the dev KYA issuer key pair in .dev-keys/
	.venv/bin/python scripts/kya_dev_issuer.py keys

image: ## Build the container image
	docker build -t agent-payments:dev .

# ---------- local cluster (kind) ----------
local-up: image ## kind cluster + Prometheus/Grafana + Postgres + payments
	kind create cluster --config local/kind.yaml
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null && helm repo update >/dev/null
	helm upgrade --install kps prometheus-community/kube-prometheus-stack --version $(KPS_VERSION) \
	  -n monitoring --create-namespace -f local/kps-values.yaml --wait --timeout 10m
	kind load docker-image agent-payments:dev --name payments
	kubectl create namespace $(NS) --dry-run=client -o yaml | kubectl apply -f -
	$(MAKE) local-secrets
	kubectl apply -f local/postgres.yaml
	kubectl -n $(NS) rollout status deploy/postgres --timeout=120s
	$(MAKE) local-deploy

local-secrets: ## Create local Secrets (random DB password, dev KYA public key)
	@test -f .dev-keys/issuer.pub || $(MAKE) keys
	@pw=$$(kubectl -n $(NS) get secret postgres-local -o jsonpath='{.data.password}' 2>/dev/null | base64 --decode); \
	[ -n "$$pw" ] || pw=$$(openssl rand -hex 16); \
	kubectl -n $(NS) create secret generic postgres-local --from-literal=password=$$pw --dry-run=client -o yaml | kubectl apply -f -; \
	kubectl -n $(NS) create secret generic payments-secrets \
	  --from-literal=database-url="postgresql+psycopg://payments:$$pw@postgres:5432/payments" \
	  --from-file=kya-public-key=.dev-keys/issuer.pub --dry-run=client -o yaml | kubectl apply -f -

local-deploy: ## Helm install/upgrade the API on kind
	helm upgrade --install payments deploy/helm/payments -n $(NS) -f deploy/helm/payments/values-local.yaml --wait --timeout 5m
	kubectl -n $(NS) get pods -o wide

port-forward: ## API on http://localhost:8080
	kubectl -n $(NS) port-forward svc/payments 8080:80

loadgen: ## Steady traffic (needs port-forward): make loadgen RPS=20 DURATION=600
	.venv/bin/python scripts/loadgen.py --rps $${RPS:-10} --duration $${DURATION:-300}

chaos: ## Database outage drill: readiness fails, alert fires, recovery
	./scripts/chaos-db-outage.sh

grafana: ## Grafana on http://localhost:3000
	@echo "user: admin  password: $$(kubectl -n monitoring get secret kps-grafana -o jsonpath='{.data.admin-password}' | base64 --decode)"
	kubectl -n monitoring port-forward svc/kps-grafana 3000:80

local-down: ## Delete the kind cluster
	kind delete cluster --name payments

# ---------- AWS ----------
aws-init: ## terraform init (infra/aws)
	terraform -chdir=infra/aws init

aws-plan: ## terraform plan
	terraform -chdir=infra/aws plan

aws-up: ## terraform apply (prompts). ~20 min. Starts EKS, NAT and RDS billing.
	terraform -chdir=infra/aws apply

aws-kubeconfig: ## kubectl context for the EKS cluster
	aws eks update-kubeconfig --name $$(terraform -chdir=infra/aws output -raw cluster_name) --region $$(terraform -chdir=infra/aws output -raw region)

argocd: ## Install Argo CD and hand the cluster to Git (root app-of-apps)
	helm repo add argo https://argoproj.github.io/argo-helm >/dev/null && helm repo update >/dev/null
	helm upgrade --install argocd argo/argo-cd --version $(ARGOCD_VERSION) -n argocd --create-namespace --wait
	kubectl apply -f deploy/argocd/root.yaml

aws-down: ## Destroy AWS resources (prompts). Remove Argo apps first so load balancers are cleaned up.
	-kubectl -n argocd delete application root --wait=true
	terraform -chdir=infra/aws destroy
