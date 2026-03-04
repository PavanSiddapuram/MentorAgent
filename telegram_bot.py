"""
Telegram Bot – MentorAgent
--------------------------
Sends messages and inline keyboard prompts to the user via Telegram Bot API.
Runs in polling mode — no public URL or webhook server required.

Usage (from mentor_scheduler.py or Copilot orchestration):
    from telegram_bot import TelegramBot

    bot = TelegramBot()

    # Send a plain message
    bot.send("Good morning. Week 3 – Threshold Sweep.")

    # Send inline keyboard and wait for reply (blocking for up to timeout seconds)
    response = bot.ask_buttons(
        text="Did you complete today's core task?",
        buttons=["✅ Completed", "⚠️ Partial", "❌ Missed"],
        timeout=1800  # 30 minutes
    )

    # Send follow-up text prompt and wait for reply
    commit_link = bot.ask_text(
        prompt="Paste your commit link (or type 'no commit'):",
        timeout=300
    )

Environment variables:
    TELEGRAM_BOT_TOKEN   - From @BotFather
    TELEGRAM_CHAT_ID     - Your personal chat ID
"""

import os
import time
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


class TelegramBot:
    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        if not self.token or not self.chat_id:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env"
            )

    def _post(self, method: str, payload: dict) -> dict:
        """Send a request to the Telegram Bot API."""
        url = f"{self.base_url}/{method}"
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
        return data

    def send(self, text: str, parse_mode: str = "Markdown") -> int:
        """
        Send a plain text message. Returns the message_id.
        """
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        result = self._post("sendMessage", payload)
        msg_id = result["result"]["message_id"]
        print(f"[Telegram] Sent message {msg_id}")
        return msg_id

    def ask_buttons(
        self,
        text: str,
        buttons: list[str],
        timeout: int = 1800,
        poll_interval: int = 5,
    ) -> str:
        """
        Send a message with inline keyboard buttons.
        Polls for a callback response up to `timeout` seconds.
        Returns the button label the user pressed, or None if timed out.

        Args:
            text: Message text to display above the buttons
            buttons: List of button labels (each becomes a separate button)
            timeout: Seconds to wait for a response (default: 30 min)
            poll_interval: Seconds between poll attempts

        Returns:
            The button label string that was pressed, or None on timeout
        """
        keyboard = {
            "inline_keyboard": [
                [{"text": btn, "callback_data": btn} for btn in buttons]
            ]
        }
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "reply_markup": keyboard,
        }
        result = self._post("sendMessage", payload)
        sent_message_id = result["result"]["message_id"]

        # Get current update offset to avoid replaying old messages
        offset = self._get_latest_offset()

        deadline = time.time() + timeout
        while time.time() < deadline:
            updates = self._get_updates(offset=offset, timeout=poll_interval)
            for update in updates:
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    cb = update["callback_query"]
                    if str(cb["from"]["id"]) == str(self.chat_id) or str(
                        cb["message"]["chat"]["id"]
                    ) == str(self.chat_id):
                        data = cb["data"]
                        # Acknowledge the callback
                        self._post(
                            "answerCallbackQuery",
                            {"callback_query_id": cb["id"], "text": "Got it."},
                        )
                        # Edit the original message to show selection
                        self._post(
                            "editMessageText",
                            {
                                "chat_id": self.chat_id,
                                "message_id": sent_message_id,
                                "text": f"{text}\n\n→ {data}",
                            },
                        )
                        print(f"[Telegram] Button pressed: {data}")
                        return data
            time.sleep(0.5)

        print(f"[Telegram] Timeout waiting for button press after {timeout}s")
        return None

    def ask_text(
        self,
        prompt: str,
        timeout: int = 300,
        poll_interval: int = 5,
    ) -> str:
        """
        Send a prompt message and wait for the user's free-text reply.
        Returns the reply text, or None if timed out.

        Args:
            prompt: The prompt to send
            timeout: Seconds to wait (default: 5 min)
            poll_interval: Seconds between polls

        Returns:
            The user's reply string, or None on timeout
        """
        self.send(prompt)
        offset = self._get_latest_offset()

        deadline = time.time() + timeout
        while time.time() < deadline:
            updates = self._get_updates(offset=offset, timeout=poll_interval)
            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    msg = update["message"]
                    if str(msg.get("chat", {}).get("id")) == str(self.chat_id):
                        text = msg.get("text", "")
                        print(f"[Telegram] Received text: {text}")
                        return text
            time.sleep(0.5)

        print(f"[Telegram] Timeout waiting for text reply after {timeout}s")
        return None

    def _get_latest_offset(self) -> int:
        """Get the offset just past the last known update to avoid replaying old messages."""
        updates = self._get_updates(offset=-1, timeout=1)
        if updates:
            return updates[-1]["update_id"] + 1
        return 0

    def _get_updates(self, offset: int = 0, timeout: int = 5) -> list:
        """Long-poll for new updates from Telegram."""
        try:
            url = f"{self.base_url}/getUpdates"
            resp = requests.get(
                url,
                params={"offset": offset, "timeout": timeout},
                timeout=timeout + 5,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", [])
        except requests.exceptions.Timeout:
            return []
        except Exception as e:
            print(f"[Telegram] Poll error: {e}")
            return []


# ── CLI convenience ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Send a Telegram message")
    parser.add_argument("--message", "-m", required=True, help="Message text to send")
    parser.add_argument(
        "--buttons",
        "-b",
        nargs="+",
        help="Optional inline button labels (will wait for a press)",
    )
    args = parser.parse_args()

    bot = TelegramBot()
    if args.buttons:
        result = bot.ask_buttons(args.message, args.buttons)
        print(f"User selected: {result}")
    else:
        bot.send(args.message)
