import asyncio
import json
import logging

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from transcribe_worker import ocr
from transcribe_worker.catalog import CatalogClient
from transcribe_worker.contracts import ContractViolation, validate
from transcribe_worker.settings import Settings

logger = logging.getLogger(__name__)

RECONNECT_PAUSE_SECONDS = 2.0


class Status:
    """What the health endpoints report."""

    def __init__(self):
        self.connected = False


class Worker:
    """Takes OCR jobs from the queue one at a time and turns each into a Machine transcription.

    Every message ends settled one way or another, because with a prefetch of one an unsettled
    message would stall the worker: done or harmless duplicate -> acked; failed with tries left ->
    published again with the next attempt number and acked; failed on the last try -> the Image is
    reported failed and the message dead-lettered; breaks the contract -> dead-lettered.
    """

    def __init__(self, settings: Settings, catalog: CatalogClient, status: Status):
        self._settings = settings
        self._catalog = catalog
        self._status = status
        self._busy = asyncio.Lock()
        self._exchange = None

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
        # A plain connection, not aio-pika's "robust" one: that restores a consumer by declaring the
        # queue again with default arguments, which clash with the real queue's dead-letter settings.
        # Reconnecting here attaches to the queue the broker already holds, every time.
        lost = asyncio.Event()
        connection = await aio_pika.connect(self._settings.rabbitmq_url)
        connection.close_callbacks.add(lambda *_: lost.set())
        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=1)
            queue = await channel.get_queue(self._settings.queue, ensure=False)
            self._exchange = await channel.get_exchange(self._settings.exchange, ensure=False)
            consumer = await queue.consume(self._handle)
            self._status.connected = True
            logger.info("Waiting for jobs on %s", self._settings.queue)
            waiting = [asyncio.create_task(stop.wait()), asyncio.create_task(lost.wait())]
            await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
            for task in waiting:
                task.cancel()
            if lost.is_set():
                raise ConnectionError("The broker connection was lost")
            await queue.cancel(consumer)
            async with self._busy:  # let the job in hand finish
                pass
        self._status.connected = False

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        async with self._busy:
            try:
                await self._process(message)
            except Exception:
                logger.exception("Unexpected error, dead-lettering the message instead of stalling")
                if not message.processed:
                    await message.nack(requeue=False)

    async def _process(self, message: AbstractIncomingMessage) -> None:
        try:
            job = json.loads(message.body)
            validate("ocr.requested", job)
        except (ValueError, ContractViolation) as error:
            logger.warning("Rejected a message that breaks the ocr.requested contract: %s", error)
            await message.reject(requeue=False)
            return
        image_id, attempt = job["image_id"], job["attempt"]
        try:
            await self._transcribe(image_id)
        except Exception as error:
            await self._failed(message, image_id, attempt, error)
            return
        await message.ack()

    async def _transcribe(self, image_id: str) -> None:
        status = await self._catalog.review_status(image_id)
        if status is None:
            logger.warning("Image %s is not known to catalog-api, nothing to read", image_id)
            return
        if status != "pending":
            logger.info("Image %s is already %s, skipping this job", image_id, status)
            return
        data = await self._catalog.fetch(image_id)
        s = self._settings
        reading = await asyncio.to_thread(
            ocr.read, data, s.ocr_languages, s.max_image_side, s.max_image_pixels, s.ocr_timeout_seconds
        )
        if await self._catalog.post_result(image_id, reading):
            logger.info("Image %s read, %d characters", image_id, len(reading.text))
        else:
            logger.info("Image %s already had a result, this was a duplicate job", image_id)

    async def _failed(self, message, image_id: str, attempt: int, error: Exception) -> None:
        s = self._settings
        logger.warning("Reading image %s failed on attempt %d of %d: %s", image_id, attempt, s.max_attempts, error)
        if attempt < s.max_attempts:
            await asyncio.sleep(s.retry_backoff_seconds * 2 ** (attempt - 1))
            try:
                await self._publish_next_attempt(image_id, attempt + 1)
            except Exception:
                logger.exception("Could not queue the next attempt, putting the job back")
                await asyncio.sleep(RECONNECT_PAUSE_SECONDS)
                await message.nack(requeue=True)
                return
            await message.ack()
            return
        try:
            await self._catalog.report_failure(image_id, str(error) or type(error).__name__)
        except Exception:
            logger.exception("Could not report the failure of image %s", image_id)
        await message.reject(requeue=False)

    async def _publish_next_attempt(self, image_id: str, attempt: int) -> None:
        job = {"image_id": image_id, "attempt": attempt}
        validate("ocr.requested", job)
        await self._exchange.publish(
            aio_pika.Message(
                json.dumps(job).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=self._settings.queue,
        )
