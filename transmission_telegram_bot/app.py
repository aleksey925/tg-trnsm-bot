import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Literal

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from transmission_rpc.error import TransmissionError

from transmission_telegram_bot import config, menus, utils
from transmission_telegram_bot.logger import init_logger

logger = logging.getLogger(__name__)

AUTO_UPDATE_INTERVAL_SEC = 1
AUTO_UPDATE_DURATION_SEC = 60
AUTO_UPDATE_STATUSES = {"downloading", "seeding", "checking"}
ACTIONS_REQUIRING_AUTO_UPDATE = {"start", "verify"}

MAGNET_PATTERN = re.compile(r"magnet:\?xt=urn:btih:[^\s]+")
TORRENT_URL_PATTERN = re.compile(r"https?://[^\s]+\.torrent\b", re.IGNORECASE)

TorrentAction = Literal["view", "start", "stop", "verify", "reload"]


@dataclass(frozen=True, slots=True)
class TorrentCallback:
    torrent_id: int
    action: TorrentAction = "view"

    @classmethod
    def parse(cls, data: str) -> TorrentCallback:
        parts = data.split("_")
        return cls(
            torrent_id=int(parts[1]),
            action=parts[2] if len(parts) == 3 else "view",
        )


def get_job_name(chat_id: int, message_id: int) -> str:
    return f"torrent_update_{chat_id}_{message_id}"


def cancel_torrent_update_job(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    job_name = get_job_name(chat_id, message_id)
    jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in jobs:
        job.schedule_removal()


async def update_torrent_status(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    if job is None or not isinstance(job.data, dict):
        return

    data: dict[str, int] = job.data
    chat_id: int = data["chat_id"]
    message_id: int = data["message_id"]
    torrent_id: int = data["torrent_id"]

    data["iteration"] += 1
    elapsed = data["iteration"] * AUTO_UPDATE_INTERVAL_SEC

    try:
        status = menus.get_torrent_status(torrent_id)
    except KeyError:
        job.schedule_removal()
        return

    should_stop = status not in AUTO_UPDATE_STATUSES or elapsed >= AUTO_UPDATE_DURATION_SEC
    remaining: int | None = None if should_stop else AUTO_UPDATE_DURATION_SEC - elapsed
    if should_stop:
        job.schedule_removal()

    try:
        text, reply_markup = menus.torrent_menu(torrent_id, auto_refresh_remaining=remaining)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2",
        )
    except BadRequest:
        pass


@utils.whitelist
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = menus.menu()
    await update.message.reply_text(text)


@utils.whitelist
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = menus.add_torrent()
    await update.message.reply_text(text)


@utils.whitelist
async def memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    formatted_memory = menus.get_memory()
    await update.message.reply_text(formatted_memory)


@utils.whitelist
async def get_torrents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    torrent_list, keyboard = menus.get_torrents()
    await update.message.reply_text(torrent_list, reply_markup=keyboard, parse_mode="MarkdownV2")


@utils.whitelist
async def get_torrents_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback = query.data.split("_")
    start_point = int(callback[1])
    cancel_torrent_update_job(context, query.message.chat_id, query.message.message_id)
    torrent_list, keyboard = menus.get_torrents(start_point)
    if len(callback) == 3 and callback[2] == "reload":
        try:
            await query.edit_message_text(text=torrent_list, reply_markup=keyboard, parse_mode="MarkdownV2")
            await query.answer(text="Reloaded")
        except BadRequest:
            await query.answer(text="Nothing to reload")
    else:
        await query.answer()
        await query.edit_message_text(text=torrent_list, reply_markup=keyboard, parse_mode="MarkdownV2")


@utils.whitelist
async def torrent_menu_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cb = TorrentCallback.parse(query.data)
    chat_id = query.message.chat_id
    message_id = query.message.message_id

    if cb.action == "start":
        menus.start_torrent(cb.torrent_id)
        await query.answer(text="Started")
    elif cb.action == "stop":
        menus.stop_torrent(cb.torrent_id)
        await query.answer(text="Stopped")
    elif cb.action == "verify":
        menus.verify_torrent(cb.torrent_id)
        await query.answer(text="Verifying")

    try:
        status = menus.get_torrent_status(cb.torrent_id)
    except KeyError:
        await query.answer(text="Torrent no longer exists")
        cancel_torrent_update_job(context, chat_id, message_id)
        text, reply_markup = menus.get_torrents()
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
        return

    should_auto_update = status in AUTO_UPDATE_STATUSES or cb.action in ACTIONS_REQUIRING_AUTO_UPDATE
    auto_refresh_remaining = AUTO_UPDATE_DURATION_SEC if should_auto_update else None
    text, reply_markup = menus.torrent_menu(cb.torrent_id, auto_refresh_remaining=auto_refresh_remaining)

    cancel_torrent_update_job(context, chat_id, message_id)

    if cb.action == "reload":
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
            await query.answer(text="Reloaded")
        except BadRequest:
            await query.answer(text="Nothing to reload")
    else:
        await query.answer()
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
        except BadRequest as exc:
            if not str(exc).startswith("Message is not modified"):
                raise

    if should_auto_update:
        context.job_queue.run_repeating(
            update_torrent_status,
            interval=AUTO_UPDATE_INTERVAL_SEC,
            first=AUTO_UPDATE_INTERVAL_SEC,
            data={"chat_id": chat_id, "message_id": message_id, "torrent_id": cb.torrent_id, "iteration": 0},
            name=get_job_name(chat_id, message_id),
        )


@utils.whitelist
async def torrent_files_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback = query.data.split("_")
    torrent_id = int(callback[1])
    cancel_torrent_update_job(context, query.message.chat_id, query.message.message_id)
    try:
        text, reply_markup = menus.get_files(torrent_id)
    except KeyError:
        await query.answer(text="Torrent no longer exists")
        text, reply_markup = menus.get_torrents()
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
    else:
        if len(callback) == 3 and callback[2] == "reload":
            try:
                await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
                await query.answer(text="Reloaded")
            except BadRequest:
                await query.answer(text="Nothing to reload")
        else:
            await query.answer()
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def delete_torrent_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback = query.data.split("_")
    torrent_id = int(callback[1])
    cancel_torrent_update_job(context, query.message.chat_id, query.message.message_id)
    try:
        text, reply_markup = menus.delete_menu(torrent_id)
    except KeyError:
        await query.answer(text="Torrent no longer exists")
        text, reply_markup = menus.get_torrents()
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
    else:
        await query.answer()
        await query.edit_message_text(text=text, reply_markup=reply_markup)


@utils.whitelist
async def delete_torrent_action_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback = query.data.split("_")
    torrent_id = int(callback[1])
    cancel_torrent_update_job(context, query.message.chat_id, query.message.message_id)
    if len(callback) == 3 and callback[2] == "data":
        menus.delete_torrent(torrent_id, True)
    else:
        menus.delete_torrent(torrent_id)
    await query.answer(text="✅Deleted")
    await asyncio.sleep(0.1)
    torrent_list, keyboard = menus.get_torrents()
    if torrent_list == "Nothing to display":
        await query.delete_message()
    else:
        await query.edit_message_text(text=torrent_list, reply_markup=keyboard, parse_mode="MarkdownV2")


@utils.whitelist
async def torrent_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await context.bot.get_file(update.message.document)
    file_bytes = await file.download_as_bytearray()
    try:
        torrent = menus.add_torrent_with_file(file_bytes)
    except TransmissionError as e:
        await update.message.reply_text(f"Failed to add torrent: {e}", do_quote=True)
    else:
        await update.message.reply_text("Torrent added", do_quote=True)
        text, reply_markup = menus.add_menu(torrent.id)
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def magnet_url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.text is None:
        return
    magnet_urls = MAGNET_PATTERN.findall(update.message.text)
    for magnet_url in magnet_urls:
        try:
            torrent = menus.add_torrent_with_magnet(magnet_url)
        except TransmissionError as e:
            await update.message.reply_text(f"Failed to add torrent: {e}", do_quote=True)
            continue
        text, reply_markup = menus.add_menu(torrent.id)
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def torrent_url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.text is None:
        return
    torrent_urls = TORRENT_URL_PATTERN.findall(update.message.text)
    for torrent_url in torrent_urls:
        try:
            torrent = menus.add_torrent_with_url(torrent_url)
        except TransmissionError as e:
            await update.message.reply_text(f"Failed to add torrent: {e}", do_quote=True)
            continue

        text, reply_markup = menus.add_menu(torrent.id)
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def torrent_adding_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback = query.data.split("_")
    if len(callback) == 3:
        torrent_id = int(callback[1])
        if callback[2] == "start":
            menus.start_torrent(torrent_id)
            text, reply_markup = menus.torrent_menu(torrent_id, auto_refresh_remaining=AUTO_UPDATE_DURATION_SEC)
            await query.answer(text="✅Started")
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
            context.job_queue.run_repeating(
                update_torrent_status,
                interval=AUTO_UPDATE_INTERVAL_SEC,
                first=AUTO_UPDATE_INTERVAL_SEC,
                data={
                    "chat_id": query.message.chat_id,
                    "message_id": query.message.message_id,
                    "torrent_id": torrent_id,
                    "iteration": 0,
                },
                name=get_job_name(query.message.chat_id, query.message.message_id),
            )
        elif callback[2] == "cancel":
            menus.delete_torrent(torrent_id, True)
            await query.answer(text="✅Canceled")
            await query.edit_message_text("Torrent deleted🗑")


@utils.whitelist
async def torrent_adding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback = query.data.split("_")
    torrent_id = int(callback[1])
    text, reply_markup = menus.add_menu(torrent_id)
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def edit_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback = query.data.split("_")
    torrent_id = int(callback[1])
    file_id = int(callback[2])
    to_state = int(callback[3])
    menus.torrent_set_files(torrent_id, file_id, bool(to_state))
    await query.answer()
    text, reply_markup = menus.get_files(torrent_id)
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def select_for_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback = query.data.split("_")
    torrent_id = int(callback[1])
    text, reply_markup = menus.select_files_add_menu(torrent_id)
    await query.answer()
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def select_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    callback = query.data.split("_")
    torrent_id = int(callback[1])
    file_id = int(callback[2])
    to_state = int(callback[3])
    menus.torrent_set_files(torrent_id, file_id, bool(to_state))
    await query.answer()
    text, reply_markup = menus.select_files_add_menu(torrent_id)
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Exception while handling an update", exc_info=context.error)

    text = "Something went wrong"
    if update and update.callback_query:
        query = update.callback_query
        await query.edit_message_text(text=text, parse_mode="MarkdownV2")
    elif update and update.message:
        await update.message.reply_text(text)


def run() -> None:
    init_logger(
        log_level=config.LOG_LEVEL,
        log_format=config.LOG_FORMAT,
        log_timestamp_format=config.LOG_TIMESTAMP_FORMAT,
    )

    application = Application.builder().token(config.TOKEN).build()

    application.add_error_handler(error_handler)
    application.add_handler(MessageHandler(filters.Document.FileExtension("torrent"), torrent_file_handler))
    application.add_handler(MessageHandler(filters.Regex(MAGNET_PATTERN), magnet_url_handler))
    application.add_handler(MessageHandler(filters.Regex(TORRENT_URL_PATTERN), torrent_url_handler))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", start))
    application.add_handler(CommandHandler("add", add))
    application.add_handler(CommandHandler("memory", memory))
    application.add_handler(CommandHandler("torrents", get_torrents_command))
    application.add_handler(CallbackQueryHandler(torrent_adding, pattern=r"addmenu_.*"))
    application.add_handler(CallbackQueryHandler(select_file, pattern=r"fileselect_.*"))
    application.add_handler(CallbackQueryHandler(select_for_download, pattern=r"selectfiles_.*"))
    application.add_handler(CallbackQueryHandler(edit_file, pattern=r"editfile_.*"))
    application.add_handler(CallbackQueryHandler(torrent_adding_actions, pattern=r"torrentadd_.*"))
    application.add_handler(CallbackQueryHandler(torrent_files_inline, pattern=r"torrentsfiles_.*"))
    application.add_handler(CallbackQueryHandler(delete_torrent_inline, pattern=r"deletemenutorrent_.*"))
    application.add_handler(CallbackQueryHandler(delete_torrent_action_inline, pattern=r"deletetorrent_.*"))
    application.add_handler(CallbackQueryHandler(get_torrents_inline, pattern=r"torrentsgoto_.*"))
    application.add_handler(CallbackQueryHandler(torrent_menu_inline, pattern=r"torrent_.*"))

    application.run_polling()
