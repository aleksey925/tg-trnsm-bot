import logging

import telegram
import transmission_rpc as trans
import transmission_rpc.utils as trans_utils
from telegram.helpers import escape_markdown
from transmission_rpc.error import TransmissionError

from . import config, utils

logger = logging.getLogger(__name__)

STATUS_LIST = {
    "downloading": "⏬",
    "seeding": "✅",
    "checking": "🔁",
    "check pending": "📡",
    "stopped": "⏹️",
}

trans_client = trans.Client(
    host=config.TRANSMISSION_HOST,
    port=config.TRANSMISSION_PORT,
    username=config.TRANSMISSION_USERNAME,
    password=config.TRANSMISSION_PASSWORD,
)


def get_torrent_status(torrent_id: int) -> str:
    return trans_client.get_torrent(torrent_id).status


def start_torrent(torrent_id: int) -> None:
    trans_client.start_torrent(torrent_id)


def stop_torrent(torrent_id: int) -> None:
    trans_client.stop_torrent(torrent_id)


def verify_torrent(torrent_id: int) -> None:
    trans_client.verify_torrent(torrent_id)


def delete_torrent(torrent_id: int, data: bool = False) -> None:
    trans_client.remove_torrent(torrent_id, delete_data=data)


def torrent_set_files(torrent_id: int, file_id: int, state: bool) -> None:
    if state:
        trans_client.change_torrent(ids=torrent_id, files_wanted=[file_id])
    else:
        trans_client.change_torrent(ids=torrent_id, files_unwanted=[file_id])


def add_torrent_with_file(file: bytes | bytearray) -> trans.Torrent:
    return trans_client.add_torrent(bytes(file), paused=True)


def add_torrent_with_magnet(url: str) -> trans.Torrent:
    return trans_client.add_torrent(url, paused=True)


def add_torrent_with_url(url: str) -> trans.Torrent:
    return trans_client.add_torrent(url, paused=True)


def menu() -> str:
    text = "Commands:\n/add - add torrent\n/torrents - list all torrents\n/memory - available memory"
    return text


def add_torrent() -> str:
    return "Just send me torrent file, magnet url or link to torrent file"


def get_memory() -> str:
    size_in_bytes = None
    try:
        size_in_bytes = trans_client.free_space(trans_client.get_session().download_dir)
    except TransmissionError:
        logger.exception("Failed to get free space")

    if size_in_bytes is None:
        size, unit = "unknown", ""
    else:
        _size, unit = trans_utils.format_size(size_in_bytes)
        size = str(round(_size, 2))

    return f"Free disk space: {size} {unit}"


def torrent_menu(
    torrent_id: int, auto_refresh_remaining: int | None = None
) -> tuple[str, telegram.InlineKeyboardMarkup]:
    torrent = trans_client.get_torrent(torrent_id)
    text = f"*{escape_markdown(torrent.name, 2)}*\n"

    status = torrent.status
    if status == "checking":
        percent = round(torrent.recheck_progress * 100, 1)
        status_line = f"Checking {percent}%"
    elif status == "check pending":
        status_line = "Check pending"
    elif status == "stopped":
        downloaded_bytes = torrent.size_when_done - torrent.left_until_done
        downloaded = trans_utils.format_size(downloaded_bytes)
        total = trans_utils.format_size(torrent.size_when_done)
        percent = round(torrent.progress, 1)
        status_line = (
            f"Stopped {round(downloaded[0], 1)} {downloaded[1]} of {round(total[0], 1)} {total[1]} ({percent}%)"
        )
    elif status == "seeding":
        total = trans_utils.format_size(torrent.size_when_done)
        ul_speed = trans_utils.format_speed(torrent.rate_upload)
        uploaded = trans_utils.format_size(torrent.uploaded_ever)
        status_line = (
            f"Seeding {round(total[0], 1)} {total[1]} ↑ {round(ul_speed[0], 1)} {ul_speed[1]} "
            f"({round(uploaded[0], 1)} {uploaded[1]})"
        )
    else:
        downloaded_bytes = torrent.size_when_done - torrent.left_until_done
        downloaded = trans_utils.format_size(downloaded_bytes)
        total = trans_utils.format_size(torrent.size_when_done)
        percent = round(torrent.progress, 1)
        dl_speed = trans_utils.format_speed(torrent.rate_download)
        ul_speed = trans_utils.format_speed(torrent.rate_upload)
        uploaded = trans_utils.format_size(torrent.uploaded_ever)
        eta = utils.formated_eta(torrent)
        status_line = (
            f"Downloading {round(downloaded[0], 1)} {downloaded[1]} of {round(total[0], 1)} {total[1]} ({percent}%)\n"
            f"↓ {round(dl_speed[0], 1)} {dl_speed[1]} ↑ {round(ul_speed[0], 1)} {ul_speed[1]} "
            f"({round(uploaded[0], 1)} {uploaded[1]})"
        )
        if eta != "Unavailable":
            status_line = f"{status_line} - {eta}"

    text += escape_markdown(status_line, 2) + "\n"
    if torrent.status == "stopped":
        start_stop = telegram.InlineKeyboardButton(
            "▶️ Start",
            callback_data=f"torrent_{torrent_id}_start",
        )
    else:
        start_stop = telegram.InlineKeyboardButton(
            "⏹️ Stop",
            callback_data=f"torrent_{torrent_id}_stop",
        )
    reply_markup = telegram.InlineKeyboardMarkup(
        [
            [
                start_stop,
                telegram.InlineKeyboardButton(
                    "📂 Files",
                    callback_data=f"torrentsfiles_{torrent_id}",
                ),
            ],
            [
                telegram.InlineKeyboardButton(
                    "🔁 Verify",
                    callback_data=f"torrent_{torrent_id}_verify",
                ),
                telegram.InlineKeyboardButton(
                    "🗑 Delete",
                    callback_data=f"deletemenutorrent_{torrent_id}",
                ),
            ],
            [
                telegram.InlineKeyboardButton(
                    f"🔄 {auto_refresh_remaining}s" if auto_refresh_remaining else "🔄 Reload",
                    callback_data=f"torrent_{torrent_id}_reload",
                ),
            ],
            [
                telegram.InlineKeyboardButton(
                    "⏪ Back",
                    callback_data="torrentsgoto_0",
                )
            ],
        ]
    )
    return text, reply_markup


def get_files(torrent_id: int) -> tuple[str, telegram.InlineKeyboardMarkup]:
    max_line_len = 100
    keyboard_width = 5
    torrent = trans_client.get_torrent(torrent_id)
    if len(torrent.name) >= max_line_len:
        name = f"{torrent.name[:max_line_len]}.."
    else:
        name = torrent.name
    text = f"*{escape_markdown(name, 2)}*\n"
    text += "Files:\n"
    column = 0
    row = 0
    file_keyboard: list[list[telegram.InlineKeyboardButton]] = [[]]
    for file_id, file in enumerate(torrent.get_files()):
        raw_name = file.name.split("/")
        filename = raw_name[1] if len(raw_name) == 2 else file.name
        if len(filename) >= max_line_len:
            filename = f"{filename[:max_line_len]}.."
        file_num = escape_markdown(f"{file_id + 1}. ", 2)
        file_size_raw = trans_utils.format_size(file.size)
        file_completed_raw = trans_utils.format_size(file.completed)
        file_size = escape_markdown(
            f"{round(file_completed_raw[0], 2)} {file_completed_raw[1]}"
            f" / {round(file_size_raw[0], 2)} {file_size_raw[1]}",
            2,
        )
        file_progress = escape_markdown(f"{round(utils.file_progress(file), 1)}%", 2)
        if column >= keyboard_width:
            file_keyboard.append([])
            column = 0
            row += 1
        if file.selected:
            filename = escape_markdown(filename, 2, "PRE")
            text += f"*{file_num}*`{filename}`\n"
            button = telegram.InlineKeyboardButton(
                f"{file_id + 1}. ✅",
                callback_data=f"editfile_{torrent_id}_{file_id}_0",
            )
        else:
            filename = escape_markdown(filename, 2)
            text += f"*{file_num}*~{filename}~\n"
            button = telegram.InlineKeyboardButton(
                f"{file_id + 1}. ❌",
                callback_data=f"editfile_{torrent_id}_{file_id}_1",
            )
        text += f"Size: {file_size} {file_progress}\n"
        column += 1
        file_keyboard[row].append(button)
    delimiter = "".join("-" for _ in range(60))
    text += escape_markdown(f"{delimiter}\n", 2)
    total_size = trans_utils.format_size(torrent.total_size)
    size_when_done = trans_utils.format_size(torrent.size_when_done)
    text += escape_markdown(
        f"Size to download: {round(size_when_done[0], 2)} {size_when_done[1]}"
        f" / {round(total_size[0], 2)} {total_size[1]}",
        2,
    )
    control_buttons = [
        [
            telegram.InlineKeyboardButton(
                "🔄 Reload",
                callback_data=f"torrentsfiles_{torrent_id}_reload",
            )
        ],
        [
            telegram.InlineKeyboardButton(
                "⏪ Back",
                callback_data=f"torrent_{torrent_id}",
            )
        ],
    ]
    reply_markup = telegram.InlineKeyboardMarkup(file_keyboard + control_buttons)
    return text, reply_markup


def get_torrents(start_point: int = 0) -> tuple[str, telegram.InlineKeyboardMarkup]:
    """
    Generates list of torrents with keyboard
    """
    max_line_len = 30
    keyboard_width = 5
    page_size = 15
    torrents = trans_client.get_torrents()
    torrents_count = 1
    start_point = start_point if torrents[start_point:] else 0
    count = start_point
    keyboard: list[list[telegram.InlineKeyboardButton]] = [[]]
    column = 0
    row = 0
    torrent_list = ""
    for torrent in torrents[start_point:]:
        if torrents_count <= page_size:
            if len(torrent.name) >= max_line_len:
                name = f"{torrent.name[:max_line_len]}.."
            else:
                name = torrent.name
            name = escape_markdown(name, 2)
            number = escape_markdown(f"{count + 1}. ", 2)
            torrent_list += f"*{number}* {STATUS_LIST[torrent.status]} {name}\n"
            if column >= keyboard_width:
                keyboard.append([])
                column = 0
                row += 1
            keyboard[row].append(telegram.InlineKeyboardButton(f"{count + 1}", callback_data=f"torrent_{torrent.id}"))
            column += 1
            count += 1
            torrents_count += 1
        else:
            keyboard.append([])
            row += 1
            keyboard[row].append(
                telegram.InlineKeyboardButton(
                    "🔄 Reload",
                    callback_data=f"torrentsgoto_{start_point}_reload",
                )
            )
            keyboard.append([])
            row += 1
            if start_point:
                keyboard[row].append(
                    telegram.InlineKeyboardButton(
                        "⏪ Back",
                        callback_data=f"torrentsgoto_{start_point - page_size}",
                    )
                )
            keyboard[row].append(
                telegram.InlineKeyboardButton(
                    "Next ⏩",
                    callback_data=f"torrentsgoto_{count}",
                )
            )
            break
    else:
        keyboard.append([])
        row += 1
        keyboard[row].append(
            telegram.InlineKeyboardButton(
                "🔄 Reload",
                callback_data=f"torrentsgoto_{start_point}_reload",
            )
        )
        keyboard.append([])
        row += 1
        if start_point and torrent_list:
            keyboard[row].append(
                telegram.InlineKeyboardButton(
                    "⏪ Back",
                    callback_data=f"torrentsgoto_{start_point - page_size}",
                )
            )
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    if not torrent_list:
        torrent_list = "Nothing to display"
    return torrent_list, reply_markup


def delete_menu(torrent_id: int) -> tuple[str, telegram.InlineKeyboardMarkup]:
    torrent = trans_client.get_torrent(torrent_id)
    text = (
        "⚠️Do you really want to delete this torrent?⚠️\n"
        f"{torrent.name}\n"
        "You also can delete torrent with all downloaded data."
    )
    reply_markup = telegram.InlineKeyboardMarkup(
        [
            [
                telegram.InlineKeyboardButton(
                    "❌ Yes",
                    callback_data=f"deletetorrent_{torrent_id}",
                )
            ],
            [
                telegram.InlineKeyboardButton(
                    "❌ Yes, with data",
                    callback_data=f"deletetorrent_{torrent_id}_data",
                )
            ],
            [
                telegram.InlineKeyboardButton(
                    "⏪ Back",
                    callback_data=f"torrent_{torrent_id}",
                )
            ],
        ]
    )
    return text, reply_markup


def add_menu(torrent_id: int) -> tuple[str, telegram.InlineKeyboardMarkup]:
    torrent = trans_client.get_torrent(torrent_id)
    text = f"*{escape_markdown(torrent.name, 2)}*\n"
    total_size = trans_utils.format_size(torrent.total_size)
    size_when_done = trans_utils.format_size(torrent.size_when_done)
    raw_text = (
        f"Size to download: {round(size_when_done[0], 2)} {size_when_done[1]}"
        f" / {round(total_size[0], 2)} {total_size[1]}\n"
        f"{get_memory()}\n"
    )
    text += escape_markdown(raw_text, 2)
    reply_markup = telegram.InlineKeyboardMarkup(
        [
            [
                telegram.InlineKeyboardButton(
                    "📂 Files",
                    callback_data=f"selectfiles_{torrent_id}",
                )
            ],
            [
                telegram.InlineKeyboardButton(
                    "▶️ Start",
                    callback_data=f"torrentadd_{torrent_id}_start",
                ),
                telegram.InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data=f"torrentadd_{torrent_id}_cancel",
                ),
            ],
        ]
    )
    return text, reply_markup


def select_files_add_menu(torrent_id: int) -> tuple[str, telegram.InlineKeyboardMarkup]:
    max_line_len = 100
    keyboard_width = 5
    torrent = trans_client.get_torrent(torrent_id)
    if len(torrent.name) >= max_line_len:
        name = f"{torrent.name[:max_line_len]}.."
    else:
        name = torrent.name
    text = f"*{escape_markdown(name, 2)}*\n"
    text += "Files:\n"
    column = 0
    row = 0
    file_keyboard: list[list[telegram.InlineKeyboardButton]] = [[]]
    for file_id, file in enumerate(torrent.get_files()):
        raw_name = file.name.split("/")
        filename = raw_name[1] if len(raw_name) == 2 else file.name
        if len(filename) >= max_line_len:
            filename = f"{filename[:max_line_len]}.."
        file_num = escape_markdown(f"{file_id + 1}. ", 2)
        filename = escape_markdown(filename, 2, "PRE")
        file_size_raw = trans_utils.format_size(file.size)
        file_size = escape_markdown(f"{round(file_size_raw[0], 2)} {file_size_raw[1]}", 2)
        if column >= keyboard_width:
            file_keyboard.append([])
            column = 0
            row += 1
        if file.selected:
            text += f"*{file_num}*`{filename}`  {file_size}\n"
            button = telegram.InlineKeyboardButton(
                f"{file_id + 1}. ✅",
                callback_data=f"fileselect_{torrent_id}_{file_id}_0",
            )
        else:
            text += f"*{file_num}*~{filename}~  {file_size}\n"
            button = telegram.InlineKeyboardButton(
                f"{file_id + 1}. ❌",
                callback_data=f"fileselect_{torrent_id}_{file_id}_1",
            )
        column += 1
        file_keyboard[row].append(button)
    total_size = trans_utils.format_size(torrent.total_size)
    size_when_done = trans_utils.format_size(torrent.size_when_done)
    text += escape_markdown(
        f"Size to download: {round(size_when_done[0], 2)} {size_when_done[1]}"
        f" / {round(total_size[0], 2)} {total_size[1]}",
        2,
    )
    control_buttons = [
        [
            telegram.InlineKeyboardButton(
                "⏪ Back",
                callback_data=f"addmenu_{torrent_id}",
            )
        ],
    ]
    reply_markup = telegram.InlineKeyboardMarkup(file_keyboard + control_buttons)
    return text, reply_markup
