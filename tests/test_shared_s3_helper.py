"""Tests for shared.s3_helper module."""

import json

import boto3
import pytest
from moto import mock_aws

from shared.s3_helper import S3Helper


BUCKET_NAME = "test-bucket"


@pytest.fixture
def s3_helper():
    """Create S3Helper with mocked AWS."""
    with mock_aws():
        # Create the bucket in mock
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET_NAME)

        helper = S3Helper(BUCKET_NAME)
        yield helper


class TestS3Helper:

    def test_upload_and_download_json(self, s3_helper):
        data = {"name": "test", "items": [1, 2, 3]}

        s3_helper.upload_json("test/data.json", data)
        result = s3_helper.download_json("test/data.json")

        assert result == data

    def test_upload_and_download_text(self, s3_helper):
        content = "# Hello World\n\nThis is markdown."

        s3_helper.upload_text("docs/readme.md", content, "text/markdown")
        result = s3_helper.download_text("docs/readme.md")

        assert result == content

    def test_object_exists_true(self, s3_helper):
        s3_helper.upload_text("exists.txt", "content")
        assert s3_helper.object_exists("exists.txt") is True

    def test_object_exists_false(self, s3_helper):
        assert s3_helper.object_exists("nonexistent.txt") is False

    def test_list_objects(self, s3_helper):
        s3_helper.upload_text("prefix/a.txt", "a")
        s3_helper.upload_text("prefix/b.txt", "b")
        s3_helper.upload_text("other/c.txt", "c")

        results = s3_helper.list_objects("prefix/")
        assert len(results) == 2
        assert "prefix/a.txt" in results
        assert "prefix/b.txt" in results

    def test_delete_object(self, s3_helper):
        s3_helper.upload_text("to-delete.txt", "bye")
        assert s3_helper.object_exists("to-delete.txt") is True

        s3_helper.delete_object("to-delete.txt")
        assert s3_helper.object_exists("to-delete.txt") is False

    def test_upload_architecture_documents(self, s3_helper):
        documents = {
            "project.md": "# Project\n\nTest project",
            "architecture.md": "# Architecture\n\nMicroservices",
            "metadata.json": {"version": "1.0", "generatedBy": "test"},
        }

        s3_helper.upload_architecture_documents(documents)

        # Verify markdown
        md = s3_helper.download_text("architecture/project.md")
        assert "Test project" in md

        # Verify JSON
        meta = s3_helper.download_json("architecture/metadata.json")
        assert meta["version"] == "1.0"
