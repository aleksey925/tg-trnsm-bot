import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

from telegram import BotCommand, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown
from transmission_rpc.error import TransmissionError

from tg_trnsm_bot import config, menus, utils
from tg_trnsm_bot.context import BotContext, BotContextTypes
from tg_trnsm_bot.logger import init_logger

logger = logging.getLogger(__name__)

AUTO_UPDATE_INTERVAL_SEC = 1
AUTO_UPDATE_DURATION_SEC = 60
AUTO_UPDATE_STATUSES = {"downloading", "seeding", "checking"}
ACTIONS_REQUIRING_AUTO_UPDATE = {"start", "verify"}

MAGNET_PATTERN = re.compile(r"magnet:\?xt=urn:btih:[^\s]+")
TORRENT_URL_PATTERN = re.compile(r"https?://[^\s]+\.torrent\b", re.IGNORECASE)

monitored_torrents: dict[int, dict[str, str | float]] = {}
torrent_owners: dict[int, int] = {}  # torrent_id → user_id (who added the torrent)
_monitor_initialized = False

TorrentAction = Literal["view", "start", "stop", "verify", "reload"]


@dataclass(frozen=True, slots=True)
class TorrentCallback:
    torrent_id: int
    action: TorrentAction = "view"

    @classmethod
    def parse(cls, data: str) -> TorrentCallback:
        parts = data.split("_")
        action: TorrentAction = cast(TorrentAction, parts[2]) if len(parts) == 3 else "view"
        return cls(torrent_id=int(parts[1]), action=action)


def get_job_name(chat_id: int, message_id: int) -> str:
    return f"torrent_update_{chat_id}_{message_id}"


def cancel_torrent_update_job(context: BotContext, chat_id: int, message_id: int) -> None:
    job_name = get_job_name(chat_id, message_id)
    jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in jobs:
        job.schedule_removal()


async def update_torrent_status(context: BotContext) -> None:
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
async def start(update: Update, context: BotContext) -> None:
    assert update.message is not None
    text = menus.menu()
    await update.message.reply_text(text)


@utils.whitelist
async def add(update: Update, context: BotContext) -> None:
    assert update.message is not None
    text = menus.add_torrent()
    await update.message.reply_text(text)


@utils.whitelist
async def memory(update: Update, context: BotContext) -> None:
    assert update.message is not None
    formatted_memory = menus.get_memory()
    await update.message.reply_text(formatted_memory)


@utils.whitelist
async def get_torrents_command(update: Update, context: BotContext) -> None:
    assert update.message is not None
    torrent_list, keyboard = menus.get_torrents()
    await update.message.reply_text(torrent_list, reply_markup=keyboard, parse_mode="MarkdownV2")


@utils.whitelist
async def get_torrents_inline(update: Update, context: BotContext) -> None:
    qc = utils.get_callback_query_context(update)
    callback = qc.parse_callback()
    start_point = int(callback[1])
    cancel_torrent_update_job(context, qc.chat_id, qc.message_id)
    torrent_list, keyboard = menus.get_torrents(start_point)
    if len(callback) == 3 and callback[2] == "reload":
        try:
            await qc.query.edit_message_text(text=torrent_list, reply_markup=keyboard, parse_mode="MarkdownV2")
            await qc.query.answer(text="Reloaded")
        except BadRequest:
            await qc.query.answer(text="Nothing to reload")
    else:
        await qc.query.answer()
        await qc.query.edit_message_text(text=torrent_list, reply_markup=keyboard, parse_mode="MarkdownV2")


@utils.whitelist
async def torrent_menu_inline(update: Update, context: BotContext) -> None:
    qc = utils.get_callback_query_context(update)
    cb = TorrentCallback.parse(qc.data)

    if cb.action == "start":
        menus.start_torrent(cb.torrent_id)
        await qc.query.answer(text="Started")
    elif cb.action == "stop":
        menus.stop_torrent(cb.torrent_id)
        await qc.query.answer(text="Stopped")
    elif cb.action == "verify":
        menus.verify_torrent(cb.torrent_id)
        await qc.query.answer(text="Verifying")

    try:
        status = menus.get_torrent_status(cb.torrent_id)
    except KeyError:
        await qc.query.answer(text="Torrent no longer exists")
        cancel_torrent_update_job(context, qc.chat_id, qc.message_id)
        text, reply_markup = menus.get_torrents()
        await qc.query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
        return

    should_auto_update = status in AUTO_UPDATE_STATUSES or cb.action in ACTIONS_REQUIRING_AUTO_UPDATE
    auto_refresh_remaining = AUTO_UPDATE_DURATION_SEC if should_auto_update else None
    text, reply_markup = menus.torrent_menu(cb.torrent_id, auto_refresh_remaining=auto_refresh_remaining)

    cancel_torrent_update_job(context, qc.chat_id, qc.message_id)

    if cb.action == "reload":
        try:
            await qc.query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
            await qc.query.answer(text="Reloaded")
        except BadRequest:
            await qc.query.answer(text="Nothing to reload")
    else:
        await qc.query.answer()
        try:
            await qc.query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
        except BadRequest as exc:
            if not str(exc).startswith("Message is not modified"):
                raise

    if should_auto_update:
        context.job_queue.run_repeating(
            update_torrent_status,
            interval=AUTO_UPDATE_INTERVAL_SEC,
            first=AUTO_UPDATE_INTERVAL_SEC,
            data={"chat_id": qc.chat_id, "message_id": qc.message_id, "torrent_id": cb.torrent_id, "iteration": 0},
            name=get_job_name(qc.chat_id, qc.message_id),
        )


@utils.whitelist
async def torrent_files_inline(update: Update, context: BotContext) -> None:
    qc = utils.get_callback_query_context(update)
    callback = qc.parse_callback()
    torrent_id = int(callback[1])
    cancel_torrent_update_job(context, qc.chat_id, qc.message_id)
    try:
        text, reply_markup = menus.get_files(torrent_id)
    except KeyError:
        await qc.query.answer(text="Torrent no longer exists")
        text, reply_markup = menus.get_torrents()
        await qc.query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
    else:
        if len(callback) == 3 and callback[2] == "reload":
            try:
                await qc.query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
                await qc.query.answer(text="Reloaded")
            except BadRequest:
                await qc.query.answer(text="Nothing to reload")
        else:
            await qc.query.answer()
            await qc.query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def delete_torrent_inline(update: Update, context: BotContext) -> None:
    qc = utils.get_callback_query_context(update)
    callback = qc.parse_callback()
    torrent_id = int(callback[1])
    cancel_torrent_update_job(context, qc.chat_id, qc.message_id)
    try:
        text, reply_markup = menus.delete_menu(torrent_id)
    except KeyError:
        await qc.query.answer(text="Torrent no longer exists")
        text, reply_markup = menus.get_torrents()
        await qc.query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
    else:
        await qc.query.answer()
        await qc.query.edit_message_text(text=text, reply_markup=reply_markup)


@utils.whitelist
async def delete_torrent_action_inline(update: Update, context: BotContext) -> None:
    qc = utils.get_callback_query_context(update)
    callback = qc.parse_callback()
    torrent_id = int(callback[1])
    cancel_torrent_update_job(context, qc.chat_id, qc.message_id)
    if len(callback) == 3 and callback[2] == "data":
        menus.delete_torrent(torrent_id, True)
    else:
        menus.delete_torrent(torrent_id)
    await qc.query.answer(text="Deleted")
    await asyncio.sleep(0.1)
    torrent_list, keyboard = menus.get_torrents()
    if torrent_list == "Nothing to display":
        await qc.query.delete_message()
    else:
        await qc.query.edit_message_text(text=torrent_list, reply_markup=keyboard, parse_mode="MarkdownV2")


@utils.whitelist
async def torrent_file_handler(update: Update, context: BotContext) -> None:
    assert update.message is not None and update.message.document is not None and update.effective_user is not None
    file = await context.bot.get_file(update.message.document)
    file_bytes = await file.download_as_bytearray()
    try:
        torrent = menus.add_torrent_with_file(file_bytes)
    except TransmissionError as e:
        await update.message.reply_text(f"Failed to add torrent: {e}", do_quote=True)
    else:
        torrent_owners[torrent.id] = update.effective_user.id
        await update.message.reply_text("Torrent added", do_quote=True)
        text, reply_markup = menus.add_menu(torrent.id)
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def magnet_url_handler(update: Update, context: BotContext) -> None:
    if update.message is None or update.message.text is None or update.effective_user is None:
        return
    magnet_urls = MAGNET_PATTERN.findall(update.message.text)
    for magnet_url in magnet_urls:
        try:
            torrent = menus.add_torrent_with_magnet(magnet_url)
        except TransmissionError as e:
            await update.message.reply_text(f"Failed to add torrent: {e}", do_quote=True)
            continue
        torrent_owners[torrent.id] = update.effective_user.id
        text, reply_markup = menus.add_menu(torrent.id)
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def torrent_url_handler(update: Update, context: BotContext) -> None:
    if update.message is None or update.message.text is None or update.effective_user is None:
        return
    torrent_urls = TORRENT_URL_PATTERN.findall(update.message.text)
    for torrent_url in torrent_urls:
        try:
            torrent = menus.add_torrent_with_url(torrent_url)
        except TransmissionError as e:
            await update.message.reply_text(f"Failed to add torrent: {e}", do_quote=True)
            continue
        torrent_owners[torrent.id] = update.effective_user.id
        text, reply_markup = menus.add_menu(torrent.id)
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def torrent_adding_actions(update: Update, context: BotContext) -> None:
    qc = utils.get_callback_query_context(update)
    callback = qc.parse_callback()
    if len(callback) == 3:
        torrent_id = int(callback[1])
        if callback[2] == "start":
            menus.start_torrent(torrent_id)
            text, reply_markup = menus.torrent_menu(torrent_id, auto_refresh_remaining=AUTO_UPDATE_DURATION_SEC)
            await qc.query.answer(text="Started")
            await qc.query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")
            context.job_queue.run_repeating(
                update_torrent_status,
                interval=AUTO_UPDATE_INTERVAL_SEC,
                first=AUTO_UPDATE_INTERVAL_SEC,
                data={
                    "chat_id": qc.chat_id,
                    "message_id": qc.message_id,
                    "torrent_id": torrent_id,
                    "iteration": 0,
                },
                name=get_job_name(qc.chat_id, qc.message_id),
            )
        elif callback[2] == "cancel":
            menus.delete_torrent(torrent_id, True)
            await qc.query.answer(text="Canceled")
            await qc.query.edit_message_text("Torrent deleted")


@utils.whitelist
async def torrent_adding(update: Update, context: BotContext) -> None:
    query, data = utils.get_callback_data(update)
    callback = data.split("_")
    torrent_id = int(callback[1])
    text, reply_markup = menus.add_menu(torrent_id)
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def edit_file(update: Update, context: BotContext) -> None:
    query, data = utils.get_callback_data(update)
    callback = data.split("_")
    torrent_id = int(callback[1])
    file_id = int(callback[2])
    to_state = int(callback[3])
    menus.torrent_set_files(torrent_id, file_id, bool(to_state))
    await query.answer()
    text, reply_markup = menus.get_files(torrent_id)
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def select_for_download(update: Update, context: BotContext) -> None:
    query, data = utils.get_callback_data(update)
    callback = data.split("_")
    torrent_id = int(callback[1])
    text, reply_markup = menus.select_files_add_menu(torrent_id)
    await query.answer()
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


@utils.whitelist
async def select_file(update: Update, context: BotContext) -> None:
    query, data = utils.get_callback_data(update)
    callback = data.split("_")
    torrent_id = int(callback[1])
    file_id = int(callback[2])
    to_state = int(callback[3])
    menus.torrent_set_files(torrent_id, file_id, bool(to_state))
    await query.answer()
    text, reply_markup = menus.select_files_add_menu(torrent_id)
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="MarkdownV2")


async def send_completion_notification(context: BotContext, torrent_name: str, user_id: int | None) -> None:
    if user_id is None:
        return
    message = f"*{escape_markdown(torrent_name, 2)} downloaded*"
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        logger.warning(f"Failed to send notification to {user_id}: {e}")


async def monitor_torrent_completion(context: BotContext) -> None:
    global _monitor_initialized

    try:
        all_torrents = menus.trans_client.get_torrents()
    except Exception:
        logger.exception("Failed to get torrents list for monitoring")
        return

    if not _monitor_initialized:
        for torrent in all_torrents:
            monitored_torrents[torrent.id] = {
                "status": torrent.status,
                "progress": round(torrent.progress, 1),
            }
        _monitor_initialized = True
        logger.info(f"Initialized torrent monitor with {len(all_torrents)} torrents")
        return

    for torrent in all_torrents:
        torrent_id = torrent.id
        current_status = torrent.status
        current_progress = round(torrent.progress, 1)

        previous_state = monitored_torrents.get(torrent_id)

        if current_progress == 100.0 and current_status in ("seeding", "stopped"):
            if previous_state is None or float(previous_state["progress"]) < 100.0:
                owner_id = torrent_owners.get(torrent_id)
                await send_completion_notification(context, torrent.name, owner_id)

        monitored_torrents[torrent_id] = {
            "status": current_status,
            "progress": current_progress,
        }

    # cleanup: remove torrents that no longer exist
    current_torrent_ids = {t.id for t in all_torrents}
    removed_ids = set(monitored_torrents.keys()) - current_torrent_ids
    for torrent_id in removed_ids:
        del monitored_torrents[torrent_id]
        torrent_owners.pop(torrent_id, None)


async def error_handler(update: object, context: BotContext) -> None:
    logger.exception("Exception while handling an update", exc_info=context.error)

    text = "Something went wrong"
    if isinstance(update, Update) and update.callback_query:
        query = update.callback_query
        await query.edit_message_text(text=text, parse_mode="MarkdownV2")
    elif isinstance(update, Update) and update.message:
        await update.message.reply_text(text)


COMMANDS: dict[str, tuple[str | None, utils.Handler]] = {
    "start": (None, start),
    "menu": ("Show main menu", start),
    "add": ("Add new torrent", add),
    "torrents": ("List all torrents", get_torrents_command),
    "memory": ("Show free disk space", memory),
}


async def post_init(application: Application[Any, BotContext, Any, Any, Any, Any]) -> None:
    bot_commands = [BotCommand(name, desc) for name, (desc, _) in COMMANDS.items() if desc]
    await application.bot.set_my_commands(bot_commands)

    if config.NOTIFICATIONS_ENABLED:
        if not application.job_queue:
            raise RuntimeError("JobQueue is not configured")

        application.job_queue.run_repeating(
            monitor_torrent_completion,
            interval=config.NOTIFICATION_CHECK_INTERVAL_SEC,
            first=config.NOTIFICATION_CHECK_INTERVAL_SEC,
            name="global_torrent_monitor",
        )
        logger.info(f"Torrent completion monitoring started (interval: {config.NOTIFICATION_CHECK_INTERVAL_SEC}s)")


def run() -> None:
    init_logger(
        log_level=config.LOG_LEVEL,
        log_format=config.LOG_FORMAT,
        log_timestamp_format=config.LOG_TIMESTAMP_FORMAT,
    )

    application = Application.builder().token(config.TOKEN).context_types(BotContextTypes).post_init(post_init).build()

    for name, (_, handler) in COMMANDS.items():
        application.add_handler(CommandHandler(name, handler))

    application.add_error_handler(error_handler)
    application.add_handler(MessageHandler(filters.Document.FileExtension("torrent"), torrent_file_handler))
    application.add_handler(MessageHandler(filters.Regex(MAGNET_PATTERN), magnet_url_handler))
    application.add_handler(MessageHandler(filters.Regex(TORRENT_URL_PATTERN), torrent_url_handler))
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
