"""
Centralized configuration management.

Each agent defines a typed config dataclass that validates
environment variables at import time, failing fast if required
values are missing.
"""

import os
from dataclasses import dataclass, field


def _require(name: str) -> str:
    """Return env var value or raise with a clear message."""
    value = os.environ.get(name)
    if not value:
        raise OSError(f"Required environment variable '{name}' is not set.")
    return value


def _optional(name: str, default: str = "") -> str:
    """Return env var value or default."""
    return os.environ.get(name, default)


# ---------------------------------------------------------------------------
# Base config shared by all agents
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaseConfig:
    """Common configuration present in all agents."""

    aws_region: str = field(default_factory=lambda: _optional("AWS_REGION", "us-east-1"))


# ---------------------------------------------------------------------------
# Agent-specific configs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkflowStarterConfig(BaseConfig):
    """Configuration for the workflow-starter Lambda."""

    state_machine_arn: str = field(default_factory=lambda: _require("STATE_MACHINE_ARN"))


@dataclass(frozen=True)
class PlanningConfig(BaseConfig):
    """Configuration for the planning agent."""

    table_name: str = field(default_factory=lambda: _require("TABLE_NAME"))
    s3_bucket: str = field(default_factory=lambda: _require("S3_BUCKET"))
    bedrock_model_id: str = field(default_factory=lambda: _require("BEDROCK_MODEL_ID"))
    github_secret_name: str = field(default_factory=lambda: _require("GITHUB_SECRET_NAME"))
    github_repo_owner: str = field(default_factory=lambda: _require("GITHUB_REPO_OWNER"))
    github_repo_name: str = field(default_factory=lambda: _require("GITHUB_REPO_NAME"))


@dataclass(frozen=True)
class ArchitectureConfig(BaseConfig):
    """Configuration for the architecture agent (knowledge-base generator)."""

    bucket_name: str = field(default_factory=lambda: _require("BUCKET_NAME"))
    bedrock_model_id: str = field(default_factory=lambda: _require("BEDROCK_MODEL_ID"))
    github_secret_name: str = field(default_factory=lambda: _require("GITHUB_SECRET_NAME"))
    github_repo_owner: str = field(default_factory=lambda: _require("GITHUB_REPO_OWNER"))
    github_repo_name: str = field(default_factory=lambda: _require("GITHUB_REPO_NAME"))
    default_branch: str = field(default_factory=lambda: _optional("DEFAULT_BRANCH", "main"))


@dataclass(frozen=True)
class DevelopmentConfig(BaseConfig):
    """Configuration for the development agent."""

    table_name: str = field(default_factory=lambda: _require("TABLE_NAME"))
    bucket_name: str = field(default_factory=lambda: _require("BUCKET_NAME"))
    bedrock_model_id: str = field(default_factory=lambda: _require("BEDROCK_MODEL_ID"))
    github_secret_name: str = field(default_factory=lambda: _require("GITHUB_SECRET_NAME"))
    github_repo_owner: str = field(default_factory=lambda: _require("GITHUB_REPO_OWNER"))
    github_repo_name: str = field(default_factory=lambda: _require("GITHUB_REPO_NAME"))


@dataclass(frozen=True)
class ValidationConfig(BaseConfig):
    """Configuration for the validation agent."""

    table_name: str = field(default_factory=lambda: _require("TABLE_NAME"))
    bucket_name: str = field(default_factory=lambda: _require("BUCKET_NAME"))
    bedrock_model_id: str = field(default_factory=lambda: _require("BEDROCK_MODEL_ID"))
    # GitHub access is optional for the validation agent: when configured, it lets
    # the agent fetch actual file/parent content to verify integration (a new
    # component is really referenced by its declared parent) instead of only
    # reviewing file-status metadata. Falls back gracefully to metadata-only
    # review if these are not set, so existing deployments keep working.
    github_secret_name: str = field(default_factory=lambda: _optional("GITHUB_SECRET_NAME"))
    github_repo_owner: str = field(default_factory=lambda: _optional("GITHUB_REPO_OWNER"))
    github_repo_name: str = field(default_factory=lambda: _optional("GITHUB_REPO_NAME"))


@dataclass(frozen=True)
class ReleaseConfig(BaseConfig):
    """Configuration for the release agent."""

    table_name: str = field(default_factory=lambda: _require("TABLE_NAME"))
    bucket_name: str = field(default_factory=lambda: _require("BUCKET_NAME"))


@dataclass(frozen=True)
class DashboardApiConfig(BaseConfig):
    """Configuration for Dashboard API."""

    state_machine_arn: str = field(default_factory=lambda: _require("STATE_MACHINE_ARN"))
