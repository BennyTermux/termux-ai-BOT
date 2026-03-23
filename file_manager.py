"""
core/file_manager.py
====================
Handles all filesystem operations within the workspace.
Parses AI-generated file blocks and writes them to disk.
"""

import re
import logging
import aiofiles
from pathlib import Path
from datetime import datetime
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)

# Regex to extract file blocks from AI output
# Matches:  === FILE: path/to/file.ext ===  ...content...  === END FILE ===
FILE_BLOCK_RE = re.compile(
    r"=== FILE:\s*(.+?)\s*===\n(.*?)=== END FILE ===",
    re.DOTALL,
)


class FileManager:
    """
    Manages the workspace directory and per-project folders.
    Thread-safe async file operations.
    """

    def __init__(self):
        self.workspace = Config.WORKSPACE_DIR
        self.workspace.mkdir(parents=True, exist_ok=True)
        logger.info("Workspace initialized at: %s", self.workspace)

    # ── Project management ────────────────────────────────────

    def create_project_dir(self, project_name: str) -> Path:
        """Create a new project directory with a timestamp."""
        safe_name = self._safe_name(project_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_dir = self.workspace / f"{safe_name}_{timestamp}"
        project_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Project directory created: %s", project_dir)
        return project_dir

    def get_or_create_project_dir(self, project_name: str) -> Path:
        """Find existing project dir or create a new one."""
        safe_name = self._safe_name(project_name)
        # Look for existing project matching name prefix
        matches = sorted(self.workspace.glob(f"{safe_name}_*"))
        if matches:
            return matches[-1]  # Return most recent
        return self.create_project_dir(project_name)

    # ── Parsing AI output ─────────────────────────────────────

    def parse_file_blocks(self, ai_response: str) -> list[dict]:
        """
        Extract file blocks from AI response.

        Returns list of: {"path": "relative/path.ext", "content": "..."}
        """
        matches = FILE_BLOCK_RE.findall(ai_response)
        files = []
        for path, content in matches:
            files.append({
                "path": path.strip(),
                "content": content.rstrip("\n"),
            })
        if not files:
            logger.debug("No file blocks found in AI response")
        else:
            logger.debug("Parsed %d file(s) from AI response", len(files))
        return files

    # ── File operations ───────────────────────────────────────

    async def write_files(
        self,
        project_dir: Path,
        files: list[dict],
    ) -> list[Path]:
        """
        Write parsed file blocks to the project directory.
        Returns list of written file paths.
        """
        written = []
        for file_info in files:
            rel_path = file_info["path"]
            content = file_info["content"]
            abs_path = project_dir / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)

            await self._write_file(abs_path, content)
            written.append(abs_path)
            logger.info("Written: %s (%d bytes)", abs_path, len(content))

        return written

    async def _write_file(self, path: Path, content: str):
        """Write content to a file asynchronously."""
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(content)

    async def read_file(self, path: Path) -> Optional[str]:
        """Read a file and return its content, or None on error."""
        try:
            if path.stat().st_size > Config.MAX_FILE_SIZE_MB * 1024 * 1024:
                logger.warning("File too large to read: %s", path)
                return None
            async with aiofiles.open(path, "r", encoding="utf-8", errors="replace") as f:
                return await f.read()
        except Exception as e:
            logger.error("Failed to read file %s: %s", path, e)
            return None

    async def save_uploaded_file(self, file_bytes: bytes, filename: str) -> Path:
        """Save a file uploaded via Telegram to the uploads directory."""
        uploads_dir = self.workspace / "_uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        dest = uploads_dir / filename
        async with aiofiles.open(dest, "wb") as f:
            await f.write(file_bytes)
        logger.info("Uploaded file saved: %s", dest)
        return dest

    # ── Project listing ───────────────────────────────────────

    def list_projects(self) -> list[dict]:
        """List all projects in the workspace."""
        projects = []
        for entry in sorted(self.workspace.iterdir()):
            if entry.is_dir() and not entry.name.startswith("_"):
                files = list(entry.rglob("*"))
                file_count = sum(1 for f in files if f.is_file())
                projects.append({
                    "name": entry.name,
                    "path": entry,
                    "file_count": file_count,
                    "created": datetime.fromtimestamp(entry.stat().st_ctime),
                })
        return projects

    def list_project_files(self, project_dir: Path) -> list[Path]:
        """Return all files in a project directory."""
        return [f for f in project_dir.rglob("*") if f.is_file()]

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _safe_name(name: str) -> str:
        """Convert a project name to a safe directory name."""
        safe = re.sub(r"[^\w\-]", "_", name.lower().strip())
        return safe[:50]  # Limit length

    def get_project_summary(self, project_dir: Path) -> str:
        """Return a text summary of the project contents."""
        files = self.list_project_files(project_dir)
        if not files:
            return "Empty project"
        lines = [f"📁 {project_dir.name}", ""]
        for f in sorted(files):
            rel = f.relative_to(project_dir)
            size = f.stat().st_size
            lines.append(f"  📄 {rel} ({size:,} bytes)")
        return "\n".join(lines)
