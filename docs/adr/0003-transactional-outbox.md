# Events are published through a transactional outbox

catalog-api writes each change event to an `outbox` table in the same transaction as the data, and a relay loop in each replica publishes unsent rows to RabbitMQ using `FOR UPDATE SKIP LOCKED`. Publishing after commit was rejected because a crash between commit and publish would leave the search index stale with no trace. The cost is at-least-once delivery, so the indexer must be idempotent; `POST /reindex` remains the repair tool.
