import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["TELEGRAM_TOKEN"]
WHITELIST = [int(i.strip()) for i in os.environ["WHITELIST"].split(",")]

TRANSMISSION_HOST = os.getenv("TRANSMISSION_HOST", "127.0.0.1")
TRANSMISSION_PORT = int(os.getenv("TRANSMISSION_PORT", "9091"))
TRANSMISSION_USERNAME = os.getenv("TRANSMISSION_USERNAME")
TRANSMISSION_PASSWORD = os.getenv("TRANSMISSION_PASSWORD")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "console")
LOG_TIMESTAMP_FORMAT = os.getenv("LOG_TIMESTAMP_FORMAT", "iso")
