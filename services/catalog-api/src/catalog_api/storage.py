from collections.abc import Iterator
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from catalog_api.settings import Settings


class StorageUnavailable(Exception):
    """Object storage could not be reached or refused the request."""


class ObjectStorage:
    """The two things catalog-api needs from S3: keep a file, and hand out a short-lived address."""

    def __init__(self, settings: Settings):
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 2},
                connect_timeout=5,
                read_timeout=60,
            ),
        )

    def put(self, bucket: str, key: str, content: BinaryIO, content_type: str) -> None:
        try:
            self._client.upload_fileobj(content, bucket, key, ExtraArgs={"ContentType": content_type})
        except (BotoCoreError, ClientError) as error:
            raise StorageUnavailable(str(error)) from error

    def stream(self, bucket: str, key: str) -> Iterator[bytes]:
        """The stored file as chunks. Storage is asked first, so a failure surfaces before anything is sent."""
        try:
            body = self._client.get_object(Bucket=bucket, Key=key)["Body"]
        except (BotoCoreError, ClientError) as error:
            raise StorageUnavailable(str(error)) from error

        def chunks() -> Iterator[bytes]:
            try:
                yield from body.iter_chunks(chunk_size=1024 * 1024)
            finally:
                body.close()

        return chunks()

    def download_url(self, bucket: str, key: str, expires_in: int) -> str:
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_in
        )
