import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPERATOR_CHAT_ID = os.getenv("OPERATOR_CHAT_ID", "")

# Cost calculation settings
MARKUP_PERCENT = 0.25  # 25% markup on product price
SHIPPING_TO_RUSSIA_PER_KG = 15.0  # EUR per kg
