#!/usr/bin/env python3
"""
main.py
=======
Entry point for the Termux AI Coding Assistant.

Usage:
    python main.py

Keep alive in Termux:
    tmux new -s bot "python main.py"        # Runs in tmux session
    nohup python main.py &                   # Background process
"""

import sys
import logging
from pathlib import Path

# ── Logging setup (must be first) ────────────────────────────
from config import Config

# Ensure log directory exists
log_path = Path(Config.LOG_FILE)
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)

# ── Rich banner ───────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()
    banner = Text("🤖 Termux AI Coding Assistant", style="bold cyan")
    console.print(Panel(banner, subtitle="Starting up…", border_style="cyan"))
except ImportError:
    print("=" * 50)
    print("  Termux AI Coding Assistant  ")
    print("=" * 50)

# ── Main startup ──────────────────────────────────────────────

def main():
    # 1. Validate config
    errors = Config.validate()
    critical_errors = [e for e in errors if "TELEGRAM" in e or "API key" in e]
    warnings = [e for e in errors if e not in critical_errors]

    if critical_errors:
        for err in critical_errors:
            logger.critical("CONFIG ERROR: %s", err)
        logger.critical(
            "Fix the above errors in your .env file, then restart."
        )
        sys.exit(1)

    for warn in warnings:
        logger.warning("CONFIG WARNING: %s", warn)

    logger.info("Config OK: %s", Config.summary())

    # 2. Initialize components
    try:
        from ai import AIRouter
        ai_router = AIRouter()
        logger.info("AI router ready")
    except Exception as e:
        logger.critical("Failed to initialize AI router: %s", e)
        sys.exit(1)

    try:
        from core import FileManager
        file_manager = FileManager()
        logger.info("File manager ready: %s", Config.WORKSPACE_DIR)
    except Exception as e:
        logger.critical("Failed to initialize file manager: %s", e)
        sys.exit(1)

    try:
        from github import GitHubManager
        github_manager = GitHubManager()
    except Exception as e:
        logger.warning("GitHub manager init failed: %s", e)
        github_manager = None

    try:
        from core import TaskHandler
        task_handler = TaskHandler(
            ai_router=ai_router,
            file_manager=file_manager,
            github_manager=github_manager,
        )
        logger.info("Task handler ready (max_concurrent=%d)", Config.MAX_CONCURRENT_TASKS)
    except Exception as e:
        logger.critical("Failed to initialize task handler: %s", e)
        sys.exit(1)

    # 3. Start Telegram bot (blocking)
    try:
        from bot import TelegramBot
        bot = TelegramBot(
            ai_router=ai_router,
            file_manager=file_manager,
            task_handler=task_handler,
            github_manager=github_manager,
        )
        logger.info(
            "Telegram bot starting (authorized user: %d)",
            Config.TELEGRAM_USER_ID,
        )
        bot.run()

    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
