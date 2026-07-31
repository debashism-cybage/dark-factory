"""
S3 helper for artifact storage.

Provides upload/download operations for JSON, text, and markdown files.
Used by all agents to store plans, architecture docs, reports, and artifacts.

Usage:
    from shared.s3_helper import S3Helper

    s3 = S3Helper(bucket_name="my-bucket")
    s3.upload_json("plans/WF-123.json", {"summary": "..."})
    data = s3.download_json("plans/WF-123.json")
"""

import json
from typing import Any

import boto3
from botocore.exceptions import ClientError

from shared.logger import get_logger

logger = get_logger(__name__)


class S3Helper:
    """S3 operations for Dark Factory artifact storage."""

    def __init__(self, bucket_name: str) -> None:
        self.bucket = bucket_name
        self.client = boto3.client("s3")
        logger.info("S3Helper initialized", bucket=bucket_name)

    # -----------------------------------------------------------------------
    # Upload operations
    # -----------------------------------------------------------------------

    def upload_text(
        self,
        key: str,
        content: str,
        content_type: str = "text/plain",
    ) -> None:
        """Upload text content to S3."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType=content_type,
        )
        logger.info("Uploaded to S3", key=key, content_type=content_type)

    def upload_json(self, key: str, data: Any) -> None:
        """Upload a JSON-serializable object to S3."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(data, indent=2, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("Uploaded JSON to S3", key=key)

    def upload_markdown(self, key: str, content: str) -> None:
        """Upload markdown content to S3."""
        self.upload_text(key, content, content_type="text/markdown")

    def upload_architecture_documents(self, documents: dict[str, Any]) -> None:
        """
        Upload architecture knowledge-base documents.

        Args:
            documents: Dict of filename -> content.
                       JSON files are uploaded as JSON, others as markdown.
        """
        for filename, content in documents.items():
            key = f"architecture/{filename}"

            if filename.endswith(".json"):
                self.upload_json(key, content)
            else:
                self.upload_markdown(key, content)

        logger.info(
            "Architecture documents uploaded",
            document_count=len(documents),
            documents=list(documents.keys()),
        )

    # -----------------------------------------------------------------------
    # Download operations
    # -----------------------------------------------------------------------

    def download_text(self, key: str) -> str:
        """Download text content from S3."""
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read().decode("utf-8")

    def download_json(self, key: str) -> Any:
        """Download and parse JSON from S3."""
        return json.loads(self.download_text(key))

    # -----------------------------------------------------------------------
    # Utility operations
    # -----------------------------------------------------------------------

    def object_exists(self, key: str) -> bool:
        """Check if an object exists in the bucket."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as ex:
            if ex.response["Error"]["Code"] == "404":
                return False
            raise

    def list_objects(self, prefix: str = "") -> list[str]:
        """List object keys under a prefix."""
        response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return [obj["Key"] for obj in response.get("Contents", [])]

    def delete_object(self, key: str) -> None:
        """Delete an object from the bucket."""
        self.client.delete_object(Bucket=self.bucket, Key=key)
        logger.info("Deleted from S3", key=key)
