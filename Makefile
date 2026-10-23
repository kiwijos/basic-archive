.PHONY: cluster-tools secrets deploy smoke ocr-parallel resilience test test-db

# One-time cluster prerequisites: Traefik and metrics-server (needs helm).
cluster-tools:
	./scripts/cluster-tools.sh

# Creates the app Secrets with random values unless they already exist.
secrets:
	./scripts/create-secrets.sh

# Applies everything. Jobs are recreated because a Job's spec cannot be updated in place.
deploy: secrets
	kubectl -n ship-archive delete job catalog-api-migrate garage-init --ignore-not-found
	kubectl apply -k k8s
	kubectl -n ship-archive rollout status statefulset/postgres --timeout=180s
	kubectl -n ship-archive rollout status statefulset/garage --timeout=180s
	kubectl -n ship-archive rollout status statefulset/rabbitmq --timeout=240s
	kubectl -n ship-archive wait --for=condition=complete job/catalog-api-migrate job/garage-init --timeout=240s
	kubectl -n ship-archive rollout status deployment/catalog-api --timeout=180s
	kubectl -n ship-archive rollout status deployment/transcribe-worker --timeout=180s

smoke:
	./scripts/smoke.sh

# Scales the worker to three replicas and uploads ten pages at once, then scales it back.
ocr-parallel:
	./scripts/ocr-parallel.sh

# Restarts RabbitMQ with a job waiting, and kills catalog-api with the broker down, on the live cluster.
resilience:
	./scripts/resilience.sh

# Starts the throwaway Postgres and RabbitMQ the tests run against.
test-db:
	docker rm -f archive-test-pg archive-test-rabbit >/dev/null 2>&1 || true
	docker run -d --name archive-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=archive_test \
		-p 55432:5432 postgres:16-alpine
	docker run -d --name archive-test-rabbit -p 56672:5672 rabbitmq:4.3.7-alpine

# The worker tests run real Tesseract; point TESSDATA_PREFIX at a directory with eng and swe data if
# your install lacks Swedish (see README).
test:
	cd services/catalog-api && uv run pytest -q
	cd services/transcribe-worker && uv run pytest -q
