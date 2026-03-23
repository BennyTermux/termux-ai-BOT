"""
bot/telegram_handler.py
=======================
Telegram bot handler.
- Enforces single-user access control
- Handles text, files, commands
- Routes to task queue for processing
- Sends formatted responses with files
"""

import asyncio
import logging
import io
from pathlib import Path
from typing import Optional

from telegram import (
    Update,
    Document,
    PhotoSize,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode, ChatAction

from config import Config
from core import FileManager, TaskHandler, Task
from ai import AIRouter
from github import GitHubManager

logger = logging.getLogger(__name__)

# Maximum characters per Telegram message
TG_MAX_LEN = 4000


class TelegramBot:
    """
    Full-featured Telegram bot with access control,
    command routing, and async task processing.
    """

    def __init__(
        self,
        ai_router: AIRouter,
        file_manager: FileManager,
        task_handler: TaskHandler,
        github_manager: GitHubManager,
    ):
        self._ai = ai_router
        self._fm = file_manager
        self._th = task_handler
        self._gh = github_manager

        # Pending project names (awaiting user input after /newproject)
        self._pending_project_name: dict[int, bool] = {}

        self._app = (
            Application.builder()
            .token(Config.TELEGRAM_BOT_TOKEN)
            .build()
        )
        self._register_handlers()
        logger.info("Telegram bot initialized")

    # ── Handler registration ──────────────────────────────────

    def _register_handlers(self):
        app = self._app

        # Commands
        app.add_handler(CommandHandler("start",      self._cmd_start))
        app.add_handler(CommandHandler("help",       self._cmd_help))
        app.add_handler(CommandHandler("newproject", self._cmd_newproject))
        app.add_handler(CommandHandler("status",     self._cmd_status))
        app.add_handler(CommandHandler("projects",   self._cmd_projects))
        app.add_handler(CommandHandler("clear",      self._cmd_clear))
        app.add_handler(CommandHandler("provider",   self._cmd_provider))

        # Files (documents + photos)
        app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        app.add_handler(MessageHandler(filters.PHOTO,        self._handle_photo))

        # Text messages (must come LAST)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))

        # Error handler
        app.add_error_handler(self._error_handler)

    # ── Access control ────────────────────────────────────────

    def _is_authorized(self, update: Update) -> bool:
        """Return True only if the message is from the configured user."""
        user_id = update.effective_user.id if update.effective_user else None
        return user_id == Config.TELEGRAM_USER_ID

    async def _reject_unauthorized(self, update: Update):
        logger.warning(
            "Unauthorized access attempt from user_id=%s",
            update.effective_user.id if update.effective_user else "unknown",
        )
        await update.message.reply_text("⛔ Unauthorized.")

    # ── Commands ──────────────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return await self._reject_unauthorized(update)
        await update.message.reply_text(
            "👋 *Welcome to your AI Coding Assistant!*\n\n"
            "Just send me a message and I'll help you build, debug, explain, or modify code.\n\n"
            "Type /help to see all commands.",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return await self._reject_unauthorized(update)
        help_text = (
            "🤖 *AI Coding Assistant — Help*\n\n"
            "*Commands:*\n"
            "/start — Welcome message\n"
            "/help — This message\n"
            "/newproject `<name>` — Start a named project\n"
            "/status — Show active tasks\n"
            "/projects — List your saved projects\n"
            "/clear — Clear conversation history\n"
            "/provider — Show current AI provider\n\n"
            "*Usage:*\n"
            "• Just type naturally to chat with the AI\n"
            "• Upload code files for analysis\n"
            "• Ask me to build, explain, or debug anything\n\n"
            "*Examples:*\n"
            '`Build me a Flask REST API with user authentication`\n'
            '`Explain this Python code` _(then upload a file)_\n'
            '`Debug this error: TypeError: ...`\n'
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_newproject(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return await self._reject_unauthorized(update)
        args = ctx.args
        project_name = " ".join(args) if args else None
        uid = update.effective_user.id

        if project_name:
            ctx.user_data["project_name"] = project_name
            await update.message.reply_text(
                f"📁 Project *{project_name}* started!\n"
                "All generated files will be saved under this project.\n"
                "What should I build?",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            self._pending_project_name[uid] = True
            await update.message.reply_text(
                "📁 What would you like to name this project?",
            )

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return await self._reject_unauthorized(update)
        status = self._th.get_status()
        await update.message.reply_text(status, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_projects(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return await self._reject_unauthorized(update)
        projects = self._fm.list_projects()
        if not projects:
            await update.message.reply_text("No projects yet. Start building something!")
            return
        lines = ["📂 *Your Projects:*\n"]
        for p in projects[-10:]:
            lines.append(
                f"• `{p['name']}` — {p['file_count']} file(s) "
                f"({p['created'].strftime('%b %d %H:%M')})"
            )
        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )

    async def _cmd_clear(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return await self._reject_unauthorized(update)
        conv_id = str(update.effective_user.id)
        self._ai.clear_history(conv_id)
        ctx.user_data.pop("project_name", None)
        await update.message.reply_text(
            "🧹 Conversation history cleared. Fresh start!"
        )

    async def _cmd_provider(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return await self._reject_unauthorized(update)
        await update.message.reply_text(
            f"🤖 Current AI: *{self._ai.get_provider_info()}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Message handlers ──────────────────────────────────────

    async def _handle_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return await self._reject_unauthorized(update)

        user_id = update.effective_user.id
        text = update.message.text.strip()

        # Check if we're waiting for a project name
        if self._pending_project_name.get(user_id):
            self._pending_project_name.pop(user_id)
            ctx.user_data["project_name"] = text
            await update.message.reply_text(
                f"📁 Project *{text}* set! Now tell me what to build.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await self._process_message(
            update=update,
            ctx=ctx,
            user_message=text,
        )

    async def _handle_document(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return await self._reject_unauthorized(update)

        doc: Document = update.message.document
        caption = update.message.caption or "Analyze this file and help me with it."

        await update.message.reply_text(
            f"📎 Received `{doc.file_name}`. Processing…",
            parse_mode=ParseMode.MARKDOWN,
        )

        # Download file
        file_content = await self._download_telegram_file(doc.file_id, doc.file_name)

        await self._process_message(
            update=update,
            ctx=ctx,
            user_message=caption,
            file_context=file_content,
            filename=doc.file_name,
        )

    async def _handle_photo(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return await self._reject_unauthorized(update)

        photo: PhotoSize = update.message.photo[-1]  # Highest resolution
        caption = update.message.caption or "Analyze this image."

        await update.message.reply_text("🖼️ Received image. Processing…")

        file_content = await self._download_telegram_file(photo.file_id, "image.jpg")

        await self._process_message(
            update=update,
            ctx=ctx,
            user_message=caption,
            file_context=f"[Image uploaded — {len(file_content)} bytes]",
            filename="image.jpg",
        )

    # ── Core processing ───────────────────────────────────────

    async def _process_message(
        self,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        user_message: str,
        file_context: Optional[str] = None,
        filename: Optional[str] = None,
    ):
        """Create a task and stream progress back to the user."""
        user_id = update.effective_user.id
        conv_id = str(user_id)

        # Show typing indicator
        await update.message.chat.send_action(ChatAction.TYPING)

        # Build task
        task = Task(
            user_message=user_message,
            conversation_id=conv_id,
            file_context=file_context,
            uploaded_filename=filename,
            project_name=ctx.user_data.get("project_name"),
        )

        # Status message we'll update
        status_msg = await update.message.reply_text(
            f"⏳ Processing task `{task.id}`…",
            parse_mode=ParseMode.MARKDOWN,
        )

        # Progress callback
        async def on_progress(t: Task, message: str):
            try:
                await status_msg.edit_text(
                    f"{message}\n_Task `{t.id}` — {t.elapsed():.0f}s_",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass  # Edit can fail if message unchanged

        # Submit task
        await self._th.submit(task, progress_cb=on_progress)

        # Wait for completion (poll)
        from core.task_handler import TaskStatus
        while task.status not in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED):
            await asyncio.sleep(1)

        # ── Send results ───────────────────────────────────────
        await self._send_task_result(update, task, status_msg)

    async def _send_task_result(self, update: Update, task: Task, status_msg):
        """Send the task result back to the user."""
        from core.task_handler import TaskStatus

        if task.status == TaskStatus.FAILED:
            await status_msg.edit_text(
                f"❌ Task failed: {task.error}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── Build response text ────────────────────────────────
        parts = []

        # AI text (strip file blocks for readability)
        clean_response = self._strip_file_blocks(task.result or "")
        if clean_response.strip():
            parts.append(clean_response.strip())

        # File summary
        if task.written_files:
            file_list = "\n".join(
                f"  📄 `{f.name}`" for f in task.written_files
            )
            parts.append(f"\n*Generated files:*\n{file_list}")

        # GitHub link
        if task.github_url:
            parts.append(f"\n🔗 [View on GitHub]({task.github_url})")

        # Timing
        parts.append(f"\n_✅ Done in {task.elapsed():.1f}s — Task `{task.id}`_")

        full_text = "\n".join(parts)

        # Delete the "Processing…" message
        try:
            await status_msg.delete()
        except Exception:
            pass

        # Send in chunks if too long
        for chunk in self._split_message(full_text):
            await update.message.reply_text(
                chunk,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False,
            )

        # ── Send generated files ───────────────────────────────
        if task.written_files:
            # Ask user if they want files sent
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📤 Send me the files",
                        callback_data=f"send_files:{task.id}",
                    )
                ]
            ])
            await update.message.reply_text(
                f"💾 {len(task.written_files)} file(s) saved locally.\n"
                "Would you like them sent to Telegram?",
                reply_markup=keyboard,
            )
            # Store task for callback retrieval
            # (In production, use persistent storage or pass via bot_data)
            self._app.bot_data.setdefault("tasks", {})[task.id] = task

    # ── Inline keyboard callback ──────────────────────────────

    async def _handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data or ""

        if data.startswith("send_files:"):
            task_id = data.split(":", 1)[1]
            task: Optional[Task] = ctx.bot_data.get("tasks", {}).get(task_id)

            if not task or not task.written_files:
                await query.edit_message_text("⚠️ Files not found.")
                return

            await query.edit_message_text("📤 Sending files…")

            for file_path in task.written_files:
                try:
                    await update.effective_message.reply_document(
                        document=open(file_path, "rb"),
                        filename=file_path.name,
                        caption=f"`{file_path.name}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception as e:
                    logger.error("Failed to send file %s: %s", file_path, e)

    # ── Utilities ─────────────────────────────────────────────

    async def _download_telegram_file(self, file_id: str, filename: str) -> str:
        """Download a Telegram file and return its text content."""
        tg_file = await self._app.bot.get_file(file_id)
        buf = io.BytesIO()
        await tg_file.download_to_memory(out=buf)
        raw = buf.getvalue()

        # Try to decode as text
        for enc in ["utf-8", "latin-1"]:
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue

        return f"[Binary file: {filename}, {len(raw)} bytes]"

    @staticmethod
    def _strip_file_blocks(text: str) -> str:
        """Remove === FILE === blocks from AI response for cleaner display."""
        import re
        clean = re.sub(
            r"=== FILE:.*?=== END FILE ===\n?",
            "",
            text,
            flags=re.DOTALL,
        )
        return clean.strip()

    @staticmethod
    def _split_message(text: str) -> list[str]:
        """Split a long message into Telegram-safe chunks."""
        if len(text) <= TG_MAX_LEN:
            return [text]
        chunks = []
        while text:
            chunk = text[:TG_MAX_LEN]
            # Try to split on a newline
            split_at = chunk.rfind("\n")
            if split_at > TG_MAX_LEN // 2:
                chunk = chunk[:split_at]
            chunks.append(chunk)
            text = text[len(chunk):]
        return chunks

    # ── Error handler ─────────────────────────────────────────

    async def _error_handler(self, update: object, ctx: ContextTypes.DEFAULT_TYPE):
        logger.error("Telegram error: %s", ctx.error, exc_info=ctx.error)
        if isinstance(update, Update) and update.message:
            try:
                await update.message.reply_text(
                    "⚠️ An internal error occurred. Please try again."
                )
            except Exception:
                pass

    # ── Run ───────────────────────────────────────────────────

    def run(self):
        """Start the bot (blocking)."""
        logger.info("Starting Telegram bot polling…")
        # Register callback handler here (needs app to exist)
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))
        self._app.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
