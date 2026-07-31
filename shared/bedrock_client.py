"""
Unified Amazon Bedrock client.

Standardizes all agent interactions with Bedrock using the Converse API.
Handles JSON response parsing, markdown fence stripping, and error handling.

Usage:
    from shared.bedrock_client import BedrockClient

    client = BedrockClient(model_id="us.amazon.nova-lite-v1:0")
    response = client.converse(system_prompt="...", user_prompt="...")
    data = client.converse_json(system_prompt="...", user_prompt="...")
"""

import json
from typing import Any

import boto3

from shared.logger import get_logger

logger = get_logger(__name__)


class BedrockClient:
    """
    Unified Bedrock client using the Converse API.

    All agents should use this single client for LLM inference.
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.client = boto3.client("bedrock-runtime")
        logger.info("BedrockClient initialized", model_id=model_id)

    def converse(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> str:
        """
        Send a single-turn conversation to Bedrock.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User message content.
            max_tokens: Maximum response tokens.
            temperature: Sampling temperature (None = model default).

        Returns:
            The model's text response.
        """
        inference_config: dict[str, Any] = {"maxTokens": max_tokens}
        if temperature is not None:
            inference_config["temperature"] = temperature

        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system_prompt}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": user_prompt}],
                }
            ],
            inferenceConfig=inference_config,
        )

        text = response["output"]["message"]["content"][0]["text"]

        logger.info(
            "Bedrock response received",
            model_id=self.model_id,
            input_tokens=response.get("usage", {}).get("inputTokens"),
            output_tokens=response.get("usage", {}).get("outputTokens"),
        )

        return text

    def converse_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """
        Send a conversation and parse the response as JSON.

        Automatically strips markdown code fences if present.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User message content.
            max_tokens: Maximum response tokens.
            temperature: Sampling temperature.

        Returns:
            Parsed JSON dictionary.

        Raises:
            ValueError: If the response cannot be parsed as valid JSON.
        """
        raw = self.converse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        cleaned = self._strip_markdown_fences(raw.strip())

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse Bedrock response as JSON",
                error=str(e),
                raw_response=raw[:500],
            )
            raise ValueError(
                f"Invalid JSON returned by Bedrock: {e}\nResponse (first 500 chars): {raw[:500]}"
            ) from e

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """Remove markdown code fences from LLM output."""
        if text.startswith("```"):
            # Remove opening fence (with optional language tag)
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            # Remove closing fence
            if text.endswith("```"):
                text = text[:-3]
            elif "```" in text:
                text = text.rsplit("```", 1)[0]
        return text.strip()
