"""
config/config_loader.py
=======================
Centralized configuration loader.
Reads from environment variables + .env file.
Never exposes secrets in logs.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env file from project root
_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)


class Config:
    """Single source of truth for all configuration values."""

    # ── Telegram ─────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_USER_ID: int = int(os.getenv("TELEGRAM_USER_ID", "0"))

    # ── AI Provider ──────────────────────────────────────────
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "claude").lower()
    AI_API_KEY: str = os.getenv("AI_API_KEY", "")

    # Per-provider keys (fallback chain)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY") or os.getenv("AI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY") or os.getenv("AI_API_KEY", "")
    GROK_API_KEY: str = os.getenv("GROK_API_KEY") or os.getenv("AI_API_KEY", "")

    # Model settings
    AI_MODEL: str = os.getenv("AI_MODEL", "")
    AI_MAX_TOKENS: int = int(os.getenv("AI_MAX_TOKENS", "4096"))
    AI_TEMPERATURE: float = float(os.getenv("AI_TEMPERATURE", "0.7"))

    # ── GitHub ───────────────────────────────────────────────
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_USERNAME: str = os.getenv("GITHUB_USERNAME", "")
    GITHUB_PRIVATE_REPOS: bool = os.getenv("GITHUB_PRIVATE_REPOS", "false").lower() == "true"

    # ── File System ──────────────────────────────────────────
    WORKSPACE_DIR: Path = Path(os.getenv("WORKSPACE_DIR", "~/ai-workspace")).expanduser()
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "10"))

    # ── Logging ──────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/bot.log")

    # ── Task Queue ───────────────────────────────────────────
    MAX_CONCURRENT_TASKS: int = int(os.getenv("MAX_CONCURRENT_TASKS", "3"))
    TASK_TIMEOUT_SECONDS: int = int(os.getenv("TASK_TIMEOUT_SECONDS", "120"))

    # ── Default models per provider ──────────────────────────
    DEFAULT_MODELS = {
        "openai":  "gpt-4o",
        "claude":  "claude-opus-4-5",
        "gemini":  "gemini-1.5-pro",
        "grok":    "grok-beta",
    }

    @classmethod
    def get_active_model(cls) -> str:
        """Return configured model or the provider default."""
        if cls.AI_MODEL:
            return cls.AI_MODEL
        return cls.DEFAULT_MODELS.get(cls.AI_PROVIDER, "unknown")

    @classmethod
    def get_api_key_for_provider(cls, provider: str) -> str:
        """Return the correct API key for the given provider."""
        mapping = {
            "openai":  cls.OPENAI_API_KEY,
            "claude":  cls.ANTHROPIC_API_KEY,
            "gemini":  cls.GEMINI_API_KEY,
            "grok":    cls.GROK_API_KEY,
        }
        return mapping.get(provider, cls.AI_API_KEY)

    @classmethod
    def validate(cls) -> list[str]:
        """
        Validate required configuration.
        Returns a list of error strings (empty = all good).
        """
        errors = []

        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN is not set")
        if not cls.TELEGRAM_USER_ID:
            errors.append("TELEGRAM_USER_ID is not set")
        if not cls.get_api_key_for_provider(cls.AI_PROVIDER):
            errors.append(f"API key for provider '{cls.AI_PROVIDER}' is not set")
        if not cls.GITHUB_TOKEN:
            errors.append("GITHUB_TOKEN is not set (GitHub integration disabled)")
        if not cls.GITHUB_USERNAME:
            errors.append("GITHUB_USERNAME is not set (GitHub integration disabled)")

        return errors

    @classmethod
    def summary(cls) -> str:
        """Return a safe (no secrets) summary for logging."""
        return (
            f"Provider={cls.AI_PROVIDER} | "
            f"Model={cls.get_active_model()} | "
            f"Workspace={cls.WORKSPACE_DIR} | "
            f"LogLevel={cls.LOG_LEVEL} | "
            f"GitHub={'✓' if cls.GITHUB_TOKEN else '✗'}"
        )
