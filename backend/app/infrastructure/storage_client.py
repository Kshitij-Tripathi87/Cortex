"""S3-compatible object storage client (MinIO locally)."""

from __future__ import annotations

import io
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import Settings


class ObjectStorageClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(
                s3={"addressing_style": "path" if settings.s3_use_path_style else "auto"}
            ),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Create only a genuinely missing bucket; surface auth/service errors."""
        try:
            self._client.head_bucket(Bucket=self.settings.s3_bucket)
        except ClientError as exc:
            error = exc.response.get("Error", {})
            code = str(error.get("Code", ""))
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self._client.create_bucket(Bucket=self.settings.s3_bucket)

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self._client.put_object(
            Bucket=self.settings.s3_bucket,
            Key=key,
            Body=io.BytesIO(data),
            ContentType=content_type,
        )

    def get_object(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self.settings.s3_bucket, Key=key)
        body: Any = resp["Body"]
        return bytes(body.read())

    def stream_object(self, key: str, chunk_size: int = 64 * 1024) -> Any:
        """Return an iterator that streams object bytes in fixed-size chunks.

        This is the streaming variant of ``get_object`` — it does NOT load the
        full object into memory, making it suitable for large files (>100MB).
        The returned iterator yields ``bytes`` chunks until the object is
        exhausted, at which point the underlying stream is closed automatically.

        Usage::

            storage = get_storage()
            for chunk in storage.stream_object(key):
                process(chunk)
        """
        resp = self._client.get_object(Bucket=self.settings.s3_bucket, Key=key)
        body: Any = resp["Body"]
        return body.iter_chunks(chunk_size)

    def object_exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.settings.s3_bucket, Key=key)
            return True
        except ClientError:
            return False

    def head_object(self, key: str) -> dict[str, Any] | None:
        try:
            resp = self._client.head_object(Bucket=self.settings.s3_bucket, Key=key)
            return dict(resp)
        except ClientError:
            return None


_storage: ObjectStorageClient | None = None


def get_storage(settings: Settings | None = None) -> ObjectStorageClient:
    global _storage
    if _storage is None:
        _storage = ObjectStorageClient(settings or get_settings_or_raise())
    return _storage


def get_settings_or_raise() -> Settings:
    from app.config import get_settings

    return get_settings()


def reset_storage() -> None:
    global _storage
    _storage = None
