import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import transmission_rpc as trans
from telegram import Update
from telegram.ext import ContextTypes

from . import config

logger = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


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
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
        user_id: int = update.effective_user.id
        if user_id not in config.WHITELIST:
            logger.warning(f"Unauthorized access denied for {user_id}.")
            return
        return await func(update, context)

    return wrapped
