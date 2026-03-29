"""Persistent cache backend — filesystem or S3-compatible. Auto-detects based on BUCKET env var."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class CacheBackend(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def put(self, key: str, data: bytes) -> None: ...
    async def exists(self, key: str) -> bool: ...


class FilesystemCache:
    """Local filesystem cache at ~/.edgarmcp/cache/"""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path.home() / ".edgarmcp" / "cache"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def get(self, key: str) -> bytes | None:
        path = self.base_dir / key
        if not path.exists():
            return None
        try:
            return await asyncio.to_thread(path.read_bytes)
        except Exception as e:
            logger.warning(f"Cache read failed for {key}: {e}")
            return None

    async def put(self, key: str, data: bytes) -> None:
        path = self.base_dir / key
        try:
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, data)
        except Exception as e:
            logger.warning(f"Cache write failed for {key}: {e}")

    async def exists(self, key: str) -> bool:
        return (self.base_dir / key).exists()

    def __repr__(self) -> str:
        return f"FilesystemCache({self.base_dir})"


class S3Cache:
    """S3-compatible cache (Railway Storage Buckets, MinIO, AWS S3)."""

    def __init__(
        self,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint: str,
        region: str = "us-east-1",
    ):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            endpoint_url=endpoint,
            region_name=region,
            config=Config(s3={"addressing_style": "virtual"}),
        )

    async def get(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self.bucket, Key=key
            )
            return await asyncio.to_thread(response["Body"].read)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            logger.warning(f"S3 cache read failed for {key}: {e}")
            return None
        except Exception as e:
            logger.warning(f"S3 cache read failed for {key}: {e}")
            return None

    async def put(self, key: str, data: bytes) -> None:
        try:
            await asyncio.to_thread(
                self._client.put_object, Bucket=self.bucket, Key=key, Body=data
            )
        except Exception as e:
            logger.warning(f"S3 cache write failed for {key}: {e}")

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(
                self._client.head_object, Bucket=self.bucket, Key=key
            )
            return True
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"S3Cache(bucket={self.bucket})"


def create_backend() -> CacheBackend:
    """Create the appropriate cache backend based on environment variables.

    If BUCKET is set (along with ACCESS_KEY_ID, SECRET_ACCESS_KEY, ENDPOINT),
    uses S3-compatible storage. Otherwise falls back to local filesystem.
    """
    bucket = os.environ.get("BUCKET")
    if bucket:
        return S3Cache(
            bucket=bucket,
            access_key_id=os.environ.get("ACCESS_KEY_ID", ""),
            secret_access_key=os.environ.get("SECRET_ACCESS_KEY", ""),
            endpoint=os.environ.get("ENDPOINT", ""),
            region=os.environ.get("REGION", "us-east-1"),
        )
    return FilesystemCache()


backend = create_backend()
