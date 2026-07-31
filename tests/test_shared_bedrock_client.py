"""Tests for shared.bedrock_client module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from shared.bedrock_client import BedrockClient


@pytest.fixture
def bedrock_client():
    """Create BedrockClient with mocked boto3 client."""
    with patch("shared.bedrock_client.boto3.client") as mock_boto:
        client = BedrockClient("us.amazon.nova-lite-v1:0")
        client.client = MagicMock()
        yield client


class TestBedrockClient:

    def test_converse_returns_text(self, bedrock_client):
        bedrock_client.client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "Hello, world!"}]
                }
            },
            "usage": {"inputTokens": 10, "outputTokens": 5},
        }

        result = bedrock_client.converse("system", "user prompt")
        assert result == "Hello, world!"

    def test_converse_json_parses_response(self, bedrock_client):
        data = {"summary": "Build auth", "requirements": ["JWT", "OAuth"]}

        bedrock_client.client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": json.dumps(data)}]
                }
            },
            "usage": {"inputTokens": 50, "outputTokens": 30},
        }

        result = bedrock_client.converse_json("system", "prompt")
        assert result == data

    def test_converse_json_strips_markdown_fences(self, bedrock_client):
        data = {"key": "value"}
        wrapped = f"```json\n{json.dumps(data)}\n```"

        bedrock_client.client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": wrapped}]
                }
            },
            "usage": {"inputTokens": 20, "outputTokens": 15},
        }

        result = bedrock_client.converse_json("system", "prompt")
        assert result == data

    def test_converse_json_raises_on_invalid_json(self, bedrock_client):
        bedrock_client.client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "not valid json at all"}]
                }
            },
            "usage": {"inputTokens": 10, "outputTokens": 10},
        }

        with pytest.raises(ValueError, match="Invalid JSON"):
            bedrock_client.converse_json("system", "prompt")

    def test_strip_markdown_fences_no_fences(self):
        text = '{"key": "value"}'
        assert BedrockClient._strip_markdown_fences(text) == text

    def test_strip_markdown_fences_with_language_tag(self):
        text = '```json\n{"key": "value"}\n```'
        assert BedrockClient._strip_markdown_fences(text) == '{"key": "value"}'
