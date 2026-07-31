"""
Centralized AWS Secrets Manager access.

Provides a simple interface to retrieve secrets with caching
to avoid repeated API calls within a single Lambda invocation.
"""

import json
from typing import Any, Optional

import boto3

from shared.logger import get_logger

logger = get_logger(__name__)

# Module-level cache (lives for the duration of the Lambda container)
_cache: dict[str, dict[str, Any]] = {}


def get_secret(secret_name: str, use_cache: bool = True) -> dict[str, Any]:
    """
    Retrieve a secret from AWS Secrets Manager.

    Args:
        secret_name: The name or ARN of the secret.
        use_cache: Whether to use the module-level cache.

    Returns:
        Parsed JSON dictionary of the secret value.
    """
    if use_cache and secret_name in _cache:
        return _cache[secret_name]

    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)
    secret_value = json.loads(response["SecretString"])

    if use_cache:
        _cache[secret_name] = secret_value

    logger.info("Secret retrieved", secret_name=secret_name)
    return secret_value


def get_github_token(secret_name: str) -> str:
    """
    Retrieve GitHub PAT from Secrets Manager.

    Handles multiple key name conventions:
    - token
    - github_token
    - GITHUB_TOKEN
    - pat

    Args:
        secret_name: The Secrets Manager secret name.

    Returns:
        The GitHub Personal Access Token string.

    Raises:
        ValueError: If no recognized token key is found.
    """
    credentials = get_secret(secret_name)

    for key in ("token", "github_token", "GITHUB_TOKEN", "pat"):
        if key in credentials and credentials[key]:
            return credentials[key]

    raise ValueError(
        f"GitHub token not found in secret '{secret_name}'. "
        f"Expected one of: token, github_token, GITHUB_TOKEN, pat"
    )
