import json
import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class S3Helper:

    def __init__(self, bucket_name):

        self.bucket = bucket_name
        self.client = boto3.client("s3")

    def upload_text(self, key, content, content_type="text/plain"):

        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType=content_type
        )

        logger.info("Uploaded s3://%s/%s", self.bucket, key)

    def upload_json(self, key, data):

        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(data, indent=2, default=str).encode("utf-8"),
            ContentType="application/json"
        )

        logger.info("Uploaded s3://%s/%s", self.bucket, key)

    def download_text(self, key):

        response = self.client.get_object(
            Bucket=self.bucket,
            Key=key
        )

        return response["Body"].read().decode("utf-8")

    def download_json(self, key):

        return json.loads(
            self.download_text(key)
        )

    def object_exists(self, key):

        try:

            self.client.head_object(
                Bucket=self.bucket,
                Key=key
            )

            return True

        except ClientError as ex:

            if ex.response["Error"]["Code"] == "404":
                return False

            raise

    def list_objects(self, prefix=""):

        response = self.client.list_objects_v2(
            Bucket=self.bucket,
            Prefix=prefix
        )

        return [
            obj["Key"]
            for obj in response.get("Contents", [])
        ]

    def delete_object(self, key):

        self.client.delete_object(
            Bucket=self.bucket,
            Key=key
        )

        logger.info("Deleted s3://%s/%s", self.bucket, key)

    def upload_architecture_documents(self, documents):

        """
        documents:
        {
            "project.md": "...",
            "architecture.md": "...",
            "repository.md": "...",
            "standards.md": "...",
            "metadata.json": {...}
        }
        """

        for filename, content in documents.items():

            key = f"architecture/{filename}"

            if filename.endswith(".json"):

                self.upload_json(
                    key,
                    content
                )

            else:

                self.upload_text(
                    key,
                    content,
                    "text/markdown"
                )