"""
ai/provider_router.py
=====================
Multi-provider AI router.
Supports: OpenAI, Anthropic (Claude), Google Gemini, Grok.
Add new providers by implementing BaseProvider and registering it.
"""

import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import Config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Base provider interface
# ─────────────────────────────────────────────────────────────────────────────

class BaseProvider(ABC):
    """All AI providers must implement this interface."""

    def __init__(self, api_key: str, model: str, max_tokens: int, temperature: float):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @abstractmethod
    async def complete(self, system_prompt: str, messages: list[dict]) -> str:
        """
        Send messages to AI and return the response text.
        messages format: [{"role": "user"|"assistant", "content": "..."}]
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Provider name for logging."""
        ...


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI provider
# ─────────────────────────────────────────────────────────────────────────────

class OpenAIProvider(BaseProvider):

    def name(self) -> str:
        return "OpenAI"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def complete(self, system_prompt: str, messages: list[dict]) -> str:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")

        client = AsyncOpenAI(api_key=self.api_key)
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        response = await client.chat.completions.create(
            model=self.model or "gpt-4o",
            messages=full_messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        return response.choices[0].message.content or ""


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic (Claude) provider
# ─────────────────────────────────────────────────────────────────────────────

class AnthropicProvider(BaseProvider):

    def name(self) -> str:
        return "Anthropic (Claude)"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def complete(self, system_prompt: str, messages: list[dict]) -> str:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

        client = anthropic.AsyncAnthropic(api_key=self.api_key)

        response = await client.messages.create(
            model=self.model or "claude-opus-4-5",
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text if response.content else ""


# ─────────────────────────────────────────────────────────────────────────────
# Google Gemini provider
# ─────────────────────────────────────────────────────────────────────────────

class GeminiProvider(BaseProvider):

    def name(self) -> str:
        return "Google Gemini"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def complete(self, system_prompt: str, messages: list[dict]) -> str:
        try:
            import google.generativeai as genai
        except ImportError:
            raise RuntimeError(
                "google-generativeai package not installed. "
                "Run: pip install google-generativeai"
            )

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(
            model_name=self.model or "gemini-1.5-pro",
            system_instruction=system_prompt,
        )

        # Convert message format
        gemini_history = []
        for msg in messages[:-1]:  # all but last
            gemini_history.append({
                "role": "user" if msg["role"] == "user" else "model",
                "parts": [msg["content"]],
            })

        last_msg = messages[-1]["content"] if messages else ""

        chat = model.start_chat(history=gemini_history)
        response = await asyncio.to_thread(
            chat.send_message,
            last_msg,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=self.max_tokens,
                temperature=self.temperature,
            ),
        )
        return response.text or ""


# ─────────────────────────────────────────────────────────────────────────────
# Grok (xAI) provider — uses OpenAI-compatible API
# ─────────────────────────────────────────────────────────────────────────────

class GrokProvider(BaseProvider):

    GROK_BASE_URL = "https://api.x.ai/v1"

    def name(self) -> str:
        return "Grok (xAI)"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def complete(self, system_prompt: str, messages: list[dict]) -> str:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")

        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.GROK_BASE_URL,
        )
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        response = await client.chat.completions.create(
            model=self.model or "grok-beta",
            messages=full_messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        return response.choices[0].message.content or ""


# ─────────────────────────────────────────────────────────────────────────────
# Provider registry & router
# ─────────────────────────────────────────────────────────────────────────────

PROVIDER_MAP: dict[str, type[BaseProvider]] = {
    "openai":  OpenAIProvider,
    "claude":  AnthropicProvider,
    "gemini":  GeminiProvider,
    "grok":    GrokProvider,
}


class AIRouter:
    """
    High-level AI client.
    Instantiate once at startup; call .chat() to get responses.
    Maintains per-conversation history.
    """

    SYSTEM_PROMPT = """You are an expert AI coding assistant deployed on a Termux Android device.
Your job is to help users write, debug, explain, and manage code across any language or framework.

When generating code:
- Always output complete, runnable files
- Use clear, consistent naming conventions
- Add helpful inline comments
- Structure multi-file projects logically

When asked to build a project:
- List all files you will create
- Output each file separately using this exact format:

=== FILE: path/to/filename.ext ===
<file content here>
=== END FILE ===

- After all files, provide a brief summary of what was built and how to run it.

Be concise but thorough. Never truncate code. If a file is long, output it completely."""

    def __init__(self):
        provider_name = Config.AI_PROVIDER
        provider_cls = PROVIDER_MAP.get(provider_name)

        if not provider_cls:
            available = ", ".join(PROVIDER_MAP.keys())
            raise ValueError(
                f"Unknown AI provider '{provider_name}'. "
                f"Available: {available}"
            )

        api_key = Config.get_api_key_for_provider(provider_name)
        if not api_key:
            raise ValueError(
                f"No API key found for provider '{provider_name}'. "
                f"Set the appropriate key in your .env file."
            )

        self._provider = provider_cls(
            api_key=api_key,
            model=Config.get_active_model(),
            max_tokens=Config.AI_MAX_TOKENS,
            temperature=Config.AI_TEMPERATURE,
        )

        # Per-conversation history: {conversation_id: [messages]}
        self._histories: dict[str, list[dict]] = {}

        logger.info(
            "AI router initialized: provider=%s model=%s",
            self._provider.name(),
            Config.get_active_model(),
        )

    async def chat(
        self,
        user_message: str,
        conversation_id: str = "default",
        system_override: Optional[str] = None,
        file_context: Optional[str] = None,
    ) -> str:
        """
        Send a message and get an AI response.

        Args:
            user_message: The user's text input.
            conversation_id: Unique ID to track conversation history.
            system_override: Override the system prompt (optional).
            file_context: Extra context from uploaded files (optional).
        """
        history = self._histories.setdefault(conversation_id, [])

        # Optionally prepend file context to user message
        content = user_message
        if file_context:
            content = f"[File context provided]\n\n{file_context}\n\n---\n\n{user_message}"

        history.append({"role": "user", "content": content})

        try:
            response = await self._provider.complete(
                system_prompt=system_override or self.SYSTEM_PROMPT,
                messages=history,
            )
        except Exception as e:
            logger.error("AI provider error: %s", e, exc_info=True)
            # Remove the failed user message from history
            history.pop()
            raise

        history.append({"role": "assistant", "content": response})

        # Limit history length to avoid token bloat (keep last 20 turns)
        if len(history) > 40:
            self._histories[conversation_id] = history[-40:]

        return response

    def clear_history(self, conversation_id: str = "default"):
        """Reset conversation history."""
        self._histories.pop(conversation_id, None)
        logger.debug("History cleared for conversation: %s", conversation_id)

    def get_provider_info(self) -> str:
        return f"{self._provider.name()} / {Config.get_active_model()}"
