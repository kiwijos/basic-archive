import asyncio
import json
import logging
import socket

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from indexer.contracts import ContractViolation, validate
from indexer.indexer import Indexer
from indexer.settings import Settings

logger = logging.getLogger(__name__)

RECONNECT_PAUSE_SECONDS = 2.0


class Status:
    """What /readyz reports: the indexes are prepared and the broker is connected."""

    def __init__(self):
        self.prepared = False
        self.connected = False

    @property
    def ready(self) -> bool:
        return self.prepared and self.connected


class Consumer:
    """Takes record.changed events one at a time and has the Indexer apply each.

    A change that keeps failing is tried max_attempts times with a growing pause and then
    dead-lettered; a reindex repairs whatever that leaves behind. A message that breaks the
    contract is dead-lettered at once.
    """

    def __init__(self, settings: Settings, indexer: Indexer, status: Status):
        self._settings = settings
        self._indexer = indexer
        self._status = status

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._consume_until(stop)
            except (aio_pika.exceptions.AMQPError, OSError) as error:
                self._status.connected = False
                logger.warning("Lost the broker, reconnecting: %s", error)
                try:
                    await asyncio.wait_for(stop.wait(), RECONNECT_PAUSE_SECONDS)
                except TimeoutError:
                    pass

    async def _consume_until(self, stop: asyncio.Event) -> None:
        # A plain connection, as in transcribe-worker: a robust one would redeclare the queue
        # without its dead-letter arguments when it reconnects.
        lost = asyncio.Event()
        connection = await aio_pika.connect(self._settings.rabbitmq_url)
        connection.close_callbacks.add(lambda *_: lost.set())
        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=1)
            queue = await channel.get_queue(self._settings.queue, ensure=False)
            # Named after the pod, so `rabbitmqctl list_consumers` shows which replica is the active one.
            consumer = await queue.consume(self._handle, consumer_tag=socket.gethostname())
            self._status.connected = True
            logger.info("Waiting for changes on %s", self._settings.queue)
            waiting = [asyncio.create_task(stop.wait()), asyncio.create_task(lost.wait())]
            await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
            for task in waiting:
                task.cancel()
            if lost.is_set():
                raise ConnectionError("The broker connection was lost")
            await queue.cancel(consumer)
            async with self._indexer.lock:  # let the change in hand finish
                pass
        self._status.connected = False

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        try:
            await self._process(message)
        except Exception:
            logger.exception("Unexpected error, dead-lettering the message instead of stalling")
            try:
                if not message.processed:
                    await message.nack(requeue=False)
            except Exception:
                logger.exception("Could not settle the message; the broker will redeliver it")

    async def _process(self, message: AbstractIncomingMessage) -> None:
        try:
            change = json.loads(message.body)
            validate("record.changed", change)
        except (ValueError, ContractViolation) as error:
            logger.warning("Rejected a message that breaks the record.changed contract: %s", error)
            await message.reject(requeue=False)
            return
        s = self._settings
        for attempt in range(1, s.max_attempts + 1):
            try:
                async with self._indexer.lock:
                    await self._indexer.apply(change["entity"], change["id"], change["op"])
                await message.ack()
                return
            except Exception as error:
                logger.warning("Applying %s failed on attempt %d of %d: %s", change, attempt, s.max_attempts, error)
                if attempt < s.max_attempts:
                    await asyncio.sleep(s.retry_backoff_seconds * 2 ** (attempt - 1))
        logger.error("Giving up on %s; it is dead-lettered and a reindex will repair it", change)
        await message.reject(requeue=False)
