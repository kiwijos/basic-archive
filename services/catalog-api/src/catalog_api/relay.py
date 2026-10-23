import json
import logging
import threading
from datetime import UTC, datetime

import pika
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from catalog_api.models import Outbox

EXCHANGE = "archive.events"
BATCH_SIZE = 50
RECONNECT_PAUSE_SECONDS = 1.0

logger = logging.getLogger(__name__)


class OutboxRelay:
    """Publishes the outbox to RabbitMQ from a thread, in every catalog-api replica.

    Rows are locked with SKIP LOCKED so replicas split the work instead of repeating it. A row is
    marked published only after the broker confirmed it, so an event is never lost; if the commit
    fails after a confirm it is published again, which consumers must tolerate (at-least-once).
    """

    def __init__(self, engine: Engine, amqp_url: str, interval_seconds: float):
        self._engine = engine
        self._parameters = pika.URLParameters(amqp_url)
        self._parameters.connection_attempts = 1
        self._parameters.socket_timeout = 5
        self._interval = interval_seconds
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name="outbox-relay", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        connection = None
        channel = None
        while not self._stopping.is_set():
            try:
                if connection is None or connection.is_closed:
                    connection = pika.BlockingConnection(self._parameters)
                    channel = connection.channel()
                    channel.confirm_delivery()
                published = self._publish_batch(channel)
            except Exception as error:
                logger.warning("Outbox relay could not publish, will retry: %s", error)
                self._close(connection)
                connection = None
                self._stopping.wait(RECONNECT_PAUSE_SECONDS)
                continue
            if published == 0:
                self._stopping.wait(self._interval)
        self._close(connection)

    @staticmethod
    def _close(connection) -> None:
        try:
            if connection is not None and connection.is_open:
                connection.close()
        except Exception:
            pass

    def _publish_batch(self, channel) -> int:
        failure = None
        with Session(self._engine) as session, session.begin():
            rows = session.scalars(
                select(Outbox)
                .where(Outbox.published_at.is_(None))
                .order_by(Outbox.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            ).all()
            published = 0
            for row in rows:
                try:
                    channel.basic_publish(
                        EXCHANGE,
                        row.event_type,
                        json.dumps(row.payload).encode(),
                        pika.BasicProperties(
                            content_type="application/json",
                            delivery_mode=pika.DeliveryMode.Persistent,
                        ),
                        mandatory=True,
                    )
                except Exception as error:
                    failure = error
                    break
                row.published_at = datetime.now(UTC)
                published += 1
        # What the broker confirmed is committed above; the rest waits for the next pass.
        if failure is not None:
            raise failure
        return published
