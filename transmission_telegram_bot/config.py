import json
import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["TELEGRAM_TOKEN"]

TRANSMISSION_HOST = os.getenv("TRANSMISSION_HOST", "127.0.0.1")
TRANSMISSION_PORT = int(os.getenv("TRANSMISSION_PORT", 9091))
TRANSMISSION_USERNAME = os.getenv("TRANSMISSION_USERNAME")
TRANSMISSION_PASSWORD = os.getenv("TRANSMISSION_PASSWORD")

_transmission_clients = os.getenv("TRANSMISSION_CLIENTS")
if _transmission_clients:
    TRANSMISSION_CLIENTS = json.loads(_transmission_clients)
else:
    TRANSMISSION_CLIENTS = [
        {
            "name": "Default",
            "host": TRANSMISSION_HOST,
            "port": TRANSMISSION_PORT,
            "username": TRANSMISSION_USERNAME,
            "password": TRANSMISSION_PASSWORD,
        }
    ]

WHITELIST = [int(i.strip()) for i in os.environ["WHITELIST"].split(",")]

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "console")
LOG_TIMESTAMP_FORMAT = os.getenv("LOG_TIMESTAMP_FORMAT", "iso")
