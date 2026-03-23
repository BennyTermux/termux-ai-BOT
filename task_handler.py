"""
core/task_handler.py
====================
Async task queue and processing pipeline.
Handles: AI requests → file generation → GitHub push → Telegram response.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Awaitable

from config import Config

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """Represents a single user request being processed."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_message: str = ""
    conversation_id: str = "default"
    file_context: Optional[str] = None      # content from uploaded file
    uploaded_filename: Optional[str] = None
    project_name: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    project_dir: Optional[Path] = None
    github_url: Optional[str] = None
    written_files: list[Path] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def elapsed(self) -> float:
        """Seconds since task started (or total if finished)."""
        if not self.started_at:
            return 0.0
        end = self.finished_at or datetime.now()
        return (end - self.started_at).total_seconds()


# Callback type: async function receiving a Task and a progress message
ProgressCallback = Callable[[Task, str], Awaitable[None]]


class TaskHandler:
    """
    Async task queue processor.
    Enforces concurrency limits and timeouts.
    """

    def __init__(self, ai_router, file_manager, github_manager):
        self._ai = ai_router
        self._fm = file_manager
        self._gh = github_manager
        self._semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_TASKS)
        self._active: dict[str, Task] = {}
        self._history: list[Task] = []

    # ── Public API ────────────────────────────────────────────

    async def submit(
        self,
        task: Task,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> Task:
        """
        Submit a task for async processing.
        progress_cb is called with status updates.
        """
        self._active[task.id] = task

        async def _run():
            async with self._semaphore:
                try:
                    await asyncio.wait_for(
                        self._process(task, progress_cb),
                        timeout=Config.TASK_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    task.status = TaskStatus.FAILED
                    task.error = f"Task timed out after {Config.TASK_TIMEOUT_SECONDS}s"
                    logger.error("Task %s timed out", task.id)
                    if progress_cb:
                        await progress_cb(task, "⏱️ Task timed out.")
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                    logger.error("Task %s failed: %s", task.id, e, exc_info=True)
                    if progress_cb:
                        await progress_cb(task, f"❌ Error: {e}")
                finally:
                    task.finished_at = datetime.now()
                    self._active.pop(task.id, None)
                    self._history.append(task)
                    # Keep only last 50 tasks in history
                    self._history = self._history[-50:]

        asyncio.create_task(_run())
        return task

    def get_status(self) -> str:
        """Return a human-readable status report."""
        lines = [
            f"🤖 *Bot Status*",
            f"Active tasks: {len(self._active)}",
            f"Completed tasks: {len(self._history)}",
            "",
        ]
        if self._active:
            lines.append("*Running:*")
            for t in self._active.values():
                lines.append(f"  • [{t.id}] {t.user_message[:40]}… ({t.elapsed():.0f}s)")
        if self._history:
            recent = self._history[-5:]
            lines.append("\n*Recent:*")
            for t in reversed(recent):
                icon = "✅" if t.status == TaskStatus.DONE else "❌"
                lines.append(f"  {icon} [{t.id}] {t.user_message[:40]}…")
        return "\n".join(lines)

    # ── Core processing pipeline ──────────────────────────────

    async def _process(self, task: Task, progress_cb: Optional[ProgressCallback]):
        """Main processing pipeline for a task."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()

        logger.info("Task [%s] started: %s", task.id, task.user_message[:60])

        # ── Step 1: Detect if this is a project build request ──
        is_project = self._is_project_request(task.user_message)

        # ── Step 2: Get AI response ────────────────────────────
        if progress_cb:
            await progress_cb(task, "🧠 Thinking…")

        ai_response = await self._ai.chat(
            user_message=task.user_message,
            conversation_id=task.conversation_id,
            file_context=task.file_context,
        )
        task.result = ai_response

        # ── Step 3: Parse file blocks if any ──────────────────
        parsed_files = self._fm.parse_file_blocks(ai_response)

        if parsed_files:
            if progress_cb:
                await progress_cb(
                    task,
                    f"📝 Writing {len(parsed_files)} file(s)…",
                )

            # Determine project name
            project_name = task.project_name or self._extract_project_name(
                task.user_message, ai_response
            )
            task.project_dir = self._fm.create_project_dir(project_name)

            # Write files to disk
            task.written_files = await self._fm.write_files(
                task.project_dir, parsed_files
            )

            # ── Step 4: GitHub push ────────────────────────────
            if self._gh and self._gh.is_configured():
                if progress_cb:
                    await progress_cb(task, "🚀 Pushing to GitHub…")
                try:
                    task.github_url = await self._gh.create_and_push(
                        project_dir=task.project_dir,
                        project_name=project_name,
                        description=self._extract_description(ai_response),
                        ai_summary=ai_response,
                    )
                except Exception as e:
                    logger.warning("GitHub push failed: %s", e)
                    if progress_cb:
                        await progress_cb(task, f"⚠️ GitHub push failed: {e}")

        task.status = TaskStatus.DONE
        logger.info(
            "Task [%s] done in %.1fs | files=%d | github=%s",
            task.id,
            task.elapsed(),
            len(task.written_files),
            task.github_url or "N/A",
        )

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _is_project_request(message: str) -> bool:
        """Heuristic: does the user want a full project built?"""
        keywords = [
            "build", "create", "make", "generate", "write a", "build me",
            "app", "project", "tool", "script", "program", "website",
        ]
        lower = message.lower()
        return any(kw in lower for kw in keywords)

    @staticmethod
    def _extract_project_name(user_message: str, ai_response: str) -> str:
        """Best-effort project name extraction."""
        # Try to find a quoted name or "called X"
        import re
        patterns = [
            r'"([^"]{3,40})"',
            r"called ([A-Za-z][A-Za-z0-9_\- ]{2,30})",
            r"named ([A-Za-z][A-Za-z0-9_\- ]{2,30})",
        ]
        for pat in patterns:
            m = re.search(pat, user_message + " " + ai_response[:200], re.IGNORECASE)
            if m:
                return m.group(1).strip()

        # Fallback: use first few significant words from user message
        words = [
            w for w in user_message.lower().split()
            if w not in {"a", "an", "the", "build", "make", "create", "me", "for", "with"}
        ]
        return "_".join(words[:4]) or "project"

    @staticmethod
    def _extract_description(ai_response: str) -> str:
        """Extract a short description from the AI response."""
        lines = [l.strip() for l in ai_response.split("\n") if l.strip()]
        # Skip file block lines
        desc_lines = [
            l for l in lines
            if not l.startswith("===") and len(l) > 20
        ]
        return desc_lines[0][:200] if desc_lines else "AI-generated project"
