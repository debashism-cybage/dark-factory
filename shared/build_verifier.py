"""
Build Verifier for the Development Agent.

Clones the target repository into a temporary directory,
applies generated code changes, detects the project type,
and runs the build to verify the code compiles.

A Pull Request is NEVER created if the build fails.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

from shared.logger import get_logger

logger = get_logger(__name__, agent="development")

# Supported build configurations
BUILD_CONFIGS = {
    "angular": {
        "detect": ["angular.json"],
        "commands": ["npm ci", "npm run build"],
    },
    "react": {
        "detect": ["react-scripts", "next.config"],
        "commands": ["npm ci", "npm run build"],
    },
    "node": {
        "detect": ["package.json"],
        "commands": ["npm ci"],
    },
    "python": {
        "detect": ["pyproject.toml", "setup.py", "requirements.txt"],
        "commands": ["pip install -r requirements.txt"],
    },
    "java_maven": {
        "detect": ["pom.xml"],
        "commands": ["mvn compile -q"],
    },
    "java_gradle": {
        "detect": ["build.gradle", "build.gradle.kts"],
        "commands": ["./gradlew build -x test"],
    },
}


class BuildVerifier:
    """
    Verifies that generated code builds successfully.

    Responsibilities:
    - Clone the repository into a temporary working directory
    - Apply generated file changes
    - Detect project type and package manager
    - Execute build commands
    - Capture stdout/stderr
    - Return structured build result
    """

    def __init__(
        self,
        repo_url: str,
        branch: str,
        token: str,
    ) -> None:
        """
        Initialize the BuildVerifier.

        Args:
            repo_url: HTTPS URL of the repository (without auth).
            branch: Branch to checkout.
            token: GitHub token for authenticated clone.
        """
        self.repo_url = repo_url
        self.branch = branch
        self.token = token
        self.work_dir: str | None = None

    def verify(
        self,
        generated_files: dict[str, str],
    ) -> dict[str, Any]:
        """
        Run build verification with the generated changes applied.

        Args:
            generated_files: Dict of file_path -> generated content.

        Returns:
            Build result dict with status, duration, and logs.
        """
        start_time = time.time()

        try:
            # Step 1: Clone repository
            self.work_dir = self._clone_repository()

            # Step 2: Apply generated changes
            self._apply_changes(generated_files)

            # Step 3: Detect project type and build commands
            build_commands = self._detect_build_commands()

            if not build_commands:
                logger.info("No build configuration detected, skipping verification")
                return {
                    "status": "BUILD_NOT_SUPPORTED",
                    "duration": time.time() - start_time,
                    "logs": "No supported build system detected. Skipping verification.",
                }

            # Step 4: Execute build
            logger.info("Build started", commands=build_commands)
            logs = self._run_commands(build_commands)

            duration = time.time() - start_time
            logger.info("Build completed", duration=f"{duration:.1f}s")

            return {
                "status": "SUCCESS",
                "duration": duration,
                "logs": logs,
            }

        except BuildFailedError as ex:
            duration = time.time() - start_time
            logger.error(
                "Build failed",
                duration=f"{duration:.1f}s",
                error=str(ex)[:500],
            )
            return {
                "status": "FAILED",
                "duration": duration,
                "logs": str(ex),
            }

        except Exception as ex:
            duration = time.time() - start_time
            logger.error(
                "Build verification error",
                duration=f"{duration:.1f}s",
                error=str(ex),
            )
            return {
                "status": "FAILED",
                "duration": duration,
                "logs": f"Build verification error: {ex}",
            }

        finally:
            self._cleanup()

    def _clone_repository(self) -> str:
        """
        Clone the repository into a temporary directory.

        Returns:
            Path to the cloned working directory.
        """
        work_dir = tempfile.mkdtemp(prefix="dark-factory-build-")

        # Construct authenticated URL
        auth_url = self.repo_url.replace("https://", f"https://x-access-token:{self.token}@")

        logger.info("Cloning repository", branch=self.branch)

        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                self.branch,
                auth_url,
                work_dir,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        if result.returncode != 0:
            # Branch might not exist remotely yet; try default branch
            shutil.rmtree(work_dir, ignore_errors=True)
            work_dir = tempfile.mkdtemp(prefix="dark-factory-build-")

            result = subprocess.run(
                ["git", "clone", "--depth", "1", auth_url, work_dir],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

            if result.returncode != 0:
                raise BuildFailedError(f"Git clone failed: {result.stderr[:500]}")

        return work_dir

    def _apply_changes(self, generated_files: dict[str, str]) -> None:
        """
        Apply generated file changes to the working directory.

        Args:
            generated_files: Dict of file_path -> content.
        """
        if not self.work_dir:
            return

        work_dir = self.work_dir

        for file_path, content in generated_files.items():
            full_path = os.path.join(work_dir, file_path)

            # Create parent directories if needed
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info("Applied change", file_path=file_path)

    def _detect_build_commands(self) -> list[str]:
        """
        Detect the project type and return appropriate build commands.

        Priority:
        1. Read package.json scripts (for Node/Angular/React projects).
        2. Check for known config files (pom.xml, build.gradle, etc.).

        Returns:
            List of shell commands to run, or empty list if unsupported.
        """
        if not self.work_dir:
            return []

        work_dir = self.work_dir

        # Check for package.json first (most common)
        package_json_path = os.path.join(work_dir, "package.json")
        if os.path.exists(package_json_path):
            return self._detect_node_build(package_json_path)

        # Check for other project types
        for config_name, config in BUILD_CONFIGS.items():
            if config_name in ("angular", "react", "node"):
                continue  # Already handled above

            for detect_file in config["detect"]:
                if os.path.exists(os.path.join(work_dir, detect_file)):
                    logger.info("Project type detected", project_type=config_name)
                    return config["commands"]

        return []

    def _detect_node_build(self, package_json_path: str) -> list[str]:
        """
        Detect Node.js build commands from package.json.

        Args:
            package_json_path: Path to package.json.

        Returns:
            List of commands to run.
        """
        work_dir = self.work_dir or ""

        try:
            with open(package_json_path, encoding="utf-8") as f:
                pkg = json.loads(f.read())
        except (json.JSONDecodeError, OSError):
            return ["npm ci"]

        scripts = pkg.get("scripts", {})

        # Detect package manager
        install_cmd = "npm ci"
        if os.path.exists(os.path.join(work_dir, "yarn.lock")):
            install_cmd = "yarn install --frozen-lockfile"
        elif os.path.exists(os.path.join(work_dir, "pnpm-lock.yaml")):
            install_cmd = "pnpm install --frozen-lockfile"

        commands = [install_cmd]

        # Detect Angular
        if os.path.exists(os.path.join(work_dir, "angular.json")):
            logger.info("Project type detected", project_type="angular")
            if "build" in scripts:
                commands.append("npm run build")
            return commands

        # Detect available build/test scripts
        if "build" in scripts:
            logger.info("Project type detected", project_type="node_with_build")
            commands.append("npm run build")
        elif "compile" in scripts:
            commands.append("npm run compile")
        elif "tsc" in scripts:
            commands.append("npm run tsc")

        # If no build script at all, just install is enough to verify deps
        if len(commands) == 1:
            logger.info("Project type detected", project_type="node_install_only")

        return commands

    def _run_commands(self, commands: list[str]) -> str:
        """
        Execute build commands sequentially.

        Args:
            commands: List of shell commands to run.

        Returns:
            Combined stdout/stderr output.

        Raises:
            BuildFailedError: If any command exits with non-zero code.
        """
        all_output: list[str] = []

        for cmd in commands:
            logger.info("Running build command", command=cmd)

            result = subprocess.run(
                cmd,
                shell=True,
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )

            output = result.stdout + result.stderr
            all_output.append(f"$ {cmd}\n{output}")

            if result.returncode != 0:
                combined = "\n".join(all_output)
                raise BuildFailedError(
                    f"Command '{cmd}' failed (exit {result.returncode}):\n{combined[-3000:]}"
                )

        return "\n".join(all_output)

    def _cleanup(self) -> None:
        """Remove the temporary working directory."""
        if self.work_dir and os.path.exists(self.work_dir):
            try:
                shutil.rmtree(self.work_dir)
                logger.info("Temporary directory cleaned up")
            except Exception as ex:
                logger.warning(
                    "Could not clean up temp directory",
                    path=self.work_dir,
                    error=str(ex),
                )


class BuildFailedError(Exception):
    """Raised when a build command fails."""
