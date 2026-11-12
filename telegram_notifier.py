import os
import logging
import requests
from typing import Optional

logger = logging.getLogger("telegram_notifier")


class TelegramNotifier:
    """
    Sends real-time trade notifications to your personal Telegram.
    Reads credentials from environment variables or keys.txt:
      TELEGRAM_BOT_TOKEN
      TELEGRAM_CHAT_ID
    """

    def __init__(self):
        self.bot_token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id: Optional[str] = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self._load_from_keys_file()

    def _load_from_keys_file(self):
        """Loads telegram credentials from keys.txt if present."""
        for filename in ["keys.txt", "key.txt"]:
            if os.path.exists(filename):
                try:
                    with open(filename, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if "=" in line and not line.startswith("#"):
                                k, v = line.split("=", 1)
                                k = k.strip().lower()
                                v = v.strip().strip('"').strip("'")
                                if k in ["telegram_bot_token", "tg_token", "bot_token"]:
                                    self.bot_token = v
                                elif k in ["telegram_chat_id", "tg_chat_id", "chat_id"]:
                                    self.chat_id = v
                except Exception as e:
                    logger.warning(f"Error reading telegram keys: {e}")

    def send_message(self, message: str) -> bool:
        """Sends an HTML formatted message to your Telegram chat."""
        self._load_from_keys_file()
        if not self.bot_token or not self.chat_id:
            logger.debug("Telegram notifications not configured. Skipping alert.")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
        }

        try:
            res = requests.post(url, json=payload, timeout=15)
            if res.status_code == 200:
                logger.info("Telegram notification delivered successfully.")
                return True
            else:
                logger.warning(f"Telegram API failed ({res.status_code}): {res.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}")
            return False

    def notify_trade_entry(self, mode: str, symbol: str, action: str, price: float, spot: float, qty: int, is_paper: bool, currency: str = "₹"):
        badge = "📝 [PAPER TRADE]" if is_paper else "⚡ [LIVE BROKER TRADE]"
        emoji = "🟢" if action == "BUY" else "🔴"
        asset_label = "Spot Price" if currency == "$" else "NIFTY Spot"
        qty_label = f"{qty} Shares" if currency == "$" else f"{qty} Qty (1 Lot)"
        text = (
            f"<b>{emoji} {badge} ENTRY</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Symbol/Contract:</b> <code>{symbol}</code>\n"
            f"<b>Action:</b> {action} ({qty_label})\n"
            f"<b>Entry Price:</b> {currency}{price:.2f}\n"
            f"<b>{asset_label}:</b> {currency}{spot:,.2f}\n"
            f"<b>Mode:</b> {mode}\n"
            f"<b>Status:</b> Active in market"
        )
        self.send_message(text)

    def notify_trade_exit(self, symbol: str, reason: str, exit_price: float, net_pnl: float, is_paper: bool, currency: str = "₹"):
        badge = "📝 [PAPER]" if is_paper else "⚡ [LIVE]"
        pnl_emoji = "🎉" if net_pnl >= 0 else "🛑"
        pnl_color = "🟢 +" if net_pnl >= 0 else "🔴 "
        text = (
            f"<b>{pnl_emoji} {badge} EXIT ({reason})</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Symbol/Contract:</b> <code>{symbol}</code>\n"
            f"<b>Exit Price:</b> {currency}{exit_price:.2f}\n"
            f"<b>Realized Net P&L:</b> <b>{pnl_color}{currency}{net_pnl:,.2f}</b>\n"
            f"<b>Reason:</b> {reason}"
        )
        self.send_message(text)

    def notify_startup(self, is_paper: bool, timeframe: str, mode: str, symbol: str = "^NSEI"):
        mode_text = "PAPER TRADING (Simulation)" if is_paper else "LIVE BROKER ACCOUNT"
        market_name = "US Equities (NYSE/NASDAQ)" if symbol != "^NSEI" else "Indian Equities (NSE)"
        text = (
            f"<b>🤖 9/21 EMA STRATEGY BOT ONLINE</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Symbol:</b> <code>{symbol}</code> ({market_name})\n"
            f"<b>Environment:</b> {mode_text}\n"
            f"<b>Timeframe:</b> {timeframe}\n"
            f"<b>Mode:</b> {mode}\n"
            f"<b>Status:</b> Actively scanning live 1-minute bars."
        )
        self.send_message(text)


# Singleton notifier
telegram_notifier = TelegramNotifier()
