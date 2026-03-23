"""
github/github_manager.py
========================
GitHub integration: create repos, write files, push commits.
Uses PyGitHub (REST API) — no git CLI needed in Termux.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from config import Config

logger = logging.getLogger(__name__)


class GitHubManager:
    """
    Manages GitHub repository creation and file uploads via REST API.
    Does NOT require git to be installed.
    """

    def __init__(self):
        self._token = Config.GITHUB_TOKEN
        self._username = Config.GITHUB_USERNAME
        self._private = Config.GITHUB_PRIVATE_REPOS
        self._gh = None  # Lazy init

        if self.is_configured():
            logger.info("GitHub manager ready for user: %s", self._username)
        else:
            logger.warning(
                "GitHub not configured (GITHUB_TOKEN or GITHUB_USERNAME missing). "
                "GitHub integration disabled."
            )

    def is_configured(self) -> bool:
        return bool(self._token and self._username)

    def _get_client(self):
        """Lazy-load the PyGithub client."""
        if self._gh is None:
            try:
                from github import Github
                self._gh = Github(self._token)
            except ImportError:
                raise RuntimeError(
                    "PyGithub not installed. Run: pip install PyGithub"
                )
        return self._gh

    # ── Public API ────────────────────────────────────────────

    async def create_and_push(
        self,
        project_dir: Path,
        project_name: str,
        description: str = "",
        ai_summary: str = "",
    ) -> str:
        """
        Create a GitHub repo and push all project files.
        Returns the repo URL.
        """
        return await asyncio.to_thread(
            self._create_and_push_sync,
            project_dir,
            project_name,
            description,
            ai_summary,
        )

    def _create_and_push_sync(
        self,
        project_dir: Path,
        project_name: str,
        description: str,
        ai_summary: str,
    ) -> str:
        """Synchronous implementation (called via asyncio.to_thread)."""
        gh = self._get_client()
        user = gh.get_user()

        repo_name = self._sanitize_repo_name(project_name)

        # Create repo (handle name conflicts with timestamp suffix)
        repo = self._create_repo(user, repo_name, description)
        logger.info("GitHub repo created: %s", repo.html_url)

        # Generate README
        readme = self._generate_readme(project_name, description, ai_summary)

        # Collect all files
        files_to_push = []

        # Add README
        files_to_push.append(("README.md", readme))

        # Add project files
        project_files = list(project_dir.rglob("*"))
        for file_path in sorted(project_files):
            if not file_path.is_file():
                continue
            rel_path = str(file_path.relative_to(project_dir))

            # Skip hidden files and large files
            if any(part.startswith(".") for part in file_path.parts[len(project_dir.parts):]):
                continue
            if file_path.stat().st_size > Config.MAX_FILE_SIZE_MB * 1024 * 1024:
                logger.warning("Skipping large file: %s", file_path)
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                files_to_push.append((rel_path, content))
            except Exception as e:
                logger.warning("Could not read %s: %s", file_path, e)

        # Push files to GitHub
        pushed = 0
        for rel_path, content in files_to_push:
            try:
                repo.create_file(
                    path=rel_path,
                    message=f"Add {rel_path}",
                    content=content,
                    branch="main",
                )
                pushed += 1
                logger.debug("Pushed: %s", rel_path)
            except Exception as e:
                logger.error("Failed to push %s: %s", rel_path, e)

        logger.info(
            "GitHub push complete: %d/%d files → %s",
            pushed,
            len(files_to_push),
            repo.html_url,
        )
        return repo.html_url

    def _create_repo(self, user, repo_name: str, description: str):
        """Create repo, handling name conflicts."""
        from github import GithubException

        try:
            return user.create_repo(
                name=repo_name,
                description=description[:200] if description else "AI-generated project",
                private=self._private,
                auto_init=False,
            )
        except GithubException as e:
            if e.status == 422:  # Name already exists
                # Try with timestamp suffix
                ts = datetime.now().strftime("%m%d%H%M")
                new_name = f"{repo_name}-{ts}"
                logger.info("Repo name taken, trying: %s", new_name)
                return user.create_repo(
                    name=new_name,
                    description=description[:200] if description else "AI-generated project",
                    private=self._private,
                    auto_init=False,
                )
            raise

    @staticmethod
    def _sanitize_repo_name(name: str) -> str:
        """Convert a project name to a valid GitHub repo name."""
        import re
        safe = re.sub(r"[^\w\-]", "-", name.lower().strip())
        safe = re.sub(r"-+", "-", safe).strip("-")
        return safe[:100] or "ai-project"

    @staticmethod
    def _generate_readme(
        project_name: str,
        description: str,
        ai_summary: str,
    ) -> str:
        """Generate a clean README.md for the project."""
        # Extract a concise summary (skip file block lines)
        summary_lines = []
        in_file_block = False
        for line in ai_summary.split("\n"):
            if line.startswith("=== FILE:"):
                in_file_block = True
                continue
            if line.startswith("=== END FILE"):
                in_file_block = False
                continue
            if not in_file_block and line.strip():
                summary_lines.append(line)
            if len(summary_lines) >= 15:
                break

        clean_summary = "\n".join(summary_lines)

        return f"""# {project_name.replace("_", " ").title()}

> {description or "AI-generated project"}

## Overview

{clean_summary}

---

## Getting Started

```bash
# Clone this repository
git clone https://github.com/{Config.GITHUB_USERNAME}/{GitHubManager._sanitize_repo_name(project_name)}.git
cd {GitHubManager._sanitize_repo_name(project_name)}
```

## Project Structure

See the files in this repository for the full project structure.

---

*Generated by [Termux AI Coding Assistant](https://github.com/{Config.GITHUB_USERNAME}) — {datetime.now().strftime("%Y-%m-%d")}*
"""
