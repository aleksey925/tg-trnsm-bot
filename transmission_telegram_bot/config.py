import json
import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["TELEGRAM_TOKEN"]

TRANSSMISION_HOST = os.getenv("TRANSSMISION_HOST", "127.0.0.1")
TRANSSMISION_PORT = int(os.getenv("TRANSSMISION_PORT", 9091))
TRANSSMISION_USERNAME = os.getenv("TRANSSMISION_USERNAME")
TRANSSMISION_PASSWORD = os.getenv("TRANSSMISION_PASSWORD")


_transmission_clients = os.getenv("TRANSMISSION_CLIENTS")
if _transmission_clients:
    TRANSMISSION_CLIENTS = json.loads(_transmission_clients)
else:
    TRANSMISSION_CLIENTS = [
        {
            "name": "Default",
            "host": TRANSSMISION_HOST,
            "port": TRANSSMISION_PORT,
            "username": TRANSSMISION_USERNAME,
            "password": TRANSSMISION_PASSWORD,
        }
    ]


_whitelist = os.environ["WHITELIST"]
WHITELIST = [int(i.strip()) for i in _whitelist.split(",")]

PROGRESS_BAR_EMOJIS = {"done": "📦", "inprogress": "⬜"}
