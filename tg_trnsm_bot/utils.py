import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import wraps
from typing import Any

import transmission_rpc as trans
from telegram import CallbackQuery, Message, Update

from . import config
from .context import BotContext

logger = logging.getLogger(__name__)

Handler = Callable[[Update, BotContext], Coroutine[Any, Any, Any]]


@dataclass(frozen=True, slots=True)
class CallbackQueryContext:
    query: CallbackQuery
    data: str
    message: Message

    @property
    def chat_id(self) -> int:
        return self.message.chat_id

    @property
    def message_id(self) -> int:
        return self.message.message_id

    def parse_callback(self) -> list[str]:
        return self.data.split("_")


def get_callback_query_context(update: Update) -> CallbackQueryContext:
    query = update.callback_query
    if query is None or query.data is None:
        raise ValueError("Invalid callback query")
    if not isinstance(query.message, Message):
        raise ValueError("Message is not accessible")
    return CallbackQueryContext(query=query, data=query.data, message=query.message)


def get_callback_data(update: Update) -> tuple[CallbackQuery, str]:
    query = update.callback_query
    if query is None or query.data is None:
        raise ValueError("Invalid callback query")
    return query, query.data


def formated_eta(torrent: trans.Torrent) -> str:
    try:
        eta = torrent.eta
    except ValueError:
        return "Unavailable"
    if eta is None:
        return "Unavailable"
    minutes, seconds = divmod(eta.seconds, 60)
    hours, minutes = divmod(minutes, 60)
    text = ""
    if eta.days:
        text += f"{eta.days} days "
    if hours:
        text += f"{hours} h {minutes} min"
    else:
        text += f"{minutes} min {seconds} sec"
    return text


def file_progress(file: trans.File) -> float:
    try:
        size = file.size
        completed = file.completed
        return 100.0 * (completed / size)
    except ZeroDivisionError:
        return 0.0


def whitelist(func: Handler) -> Handler:
    @wraps(func)
    async def wrapped(update: Update, context: BotContext) -> Any:
        if update.effective_user is None:
            logger.warning("Update has no effective_user, access denied")
            return

        user_id: int = update.effective_user.id
        if user_id not in config.WHITELIST:
            logger.warning(f"Unauthorized access denied for {user_id}.")
            return
        return await func(update, context)

    return wrapped
