.PHONY: cluster-tools secrets deploy smoke test test-db

# One-time cluster prerequisites: Traefik and metrics-server (needs helm).
cluster-tools:
	./scripts/cluster-tools.sh

# Creates the app Secrets with random values unless they already exist.
secrets:
	./scripts/create-secrets.sh

# Applies everything. The migration Job is recreated because a Job's spec cannot be updated in place.
deploy: secrets
	kubectl -n ship-archive delete job catalog-api-migrate --ignore-not-found
	kubectl apply -k k8s
	kubectl -n ship-archive rollout status statefulset/postgres --timeout=180s
	kubectl -n ship-archive wait --for=condition=complete job/catalog-api-migrate --timeout=180s
	kubectl -n ship-archive rollout status deployment/catalog-api --timeout=180s

smoke:
	./scripts/smoke.sh

# Starts the throwaway Postgres the API tests run against.
test-db:
	docker rm -f archive-test-pg >/dev/null 2>&1 || true
	docker run -d --name archive-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=archive_test \
		-p 55432:5432 postgres:16-alpine

test:
	cd services/catalog-api && uv run pytest -q
