"""
Notification Helper
-------------------
Sends notifications to terminal, Slack, and/or Telegram.

Usage:
    # Terminal only
    python notify.py --message "Updated task: Auth Module" --channel terminal

    # Slack only
    python notify.py --message "Created task: JWT Refresh" --channel slack

    # Telegram only
    python notify.py --message "Day 7 locked in. Streak: 🔥7" --channel telegram

    # All channels
    python notify.py --message "Synced commit abc123 → ClickUp task CU-xyz" --channel all

    # Legacy "both" still works (terminal + slack)
    python notify.py --message "Done" --channel both

    # With structured data (JSON)
    python notify.py --json '{"action": "updated", "task": "Auth Module", "url": "https://app.clickup.com/t/abc"}' --channel all

Environment variables:
    SLACK_WEBHOOK_URL    - Slack incoming webhook URL (required for Slack channel)
    TELEGRAM_BOT_TOKEN   - Telegram bot token (required for Telegram channel)
    TELEGRAM_CHAT_ID     - Telegram chat ID (required for Telegram channel)
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)


# ─── Terminal Notifications ────────────────────────────────

def notify_terminal(message, data=None, level="info"):
    """Print a formatted notification to terminal."""
    icons = {"info": "ℹ", "success": "✓", "warning": "⚠", "error": "✗"}
    icon = icons.get(level, "ℹ")
    timestamp = datetime.now().strftime("%H:%M:%S")

    print(f"\n{'─' * 60}")
    print(f"  {icon}  [{timestamp}] MENTOR AGENT")
    print(f"  {message}")
    if data:
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"     {k}: {v}")
        else:
            print(f"     {data}")
    print(f"{'─' * 60}\n")


# ─── Slack Notifications ──────────────────────────────────

def notify_slack(message, data=None, webhook_url=None):
    """Post a notification to Slack via incoming webhook."""
    webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("WARNING: SLACK_WEBHOOK_URL not set. Skipping Slack notification.", file=sys.stderr)
        return False

    if httpx is None:
        print("WARNING: httpx not installed. Skipping Slack notification.", file=sys.stderr)
        return False

    # Build Slack Block Kit message
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Mentor Agent", "emoji": True}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message}
        },
    ]

    if data and isinstance(data, dict):
        fields = []
        for k, v in data.items():
            fields.append({"type": "mrkdwn", "text": f"*{k}:*\n{v}"})
        # Slack allows max 10 fields, 2 per row
        for i in range(0, len(fields), 2):
            blocks.append({
                "type": "section",
                "fields": fields[i:i + 2]
            })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"_Sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_"}]
    })

    payload = {"blocks": blocks, "text": message}  # text is fallback

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(webhook_url, json=payload)
            if response.status_code == 200:
                print("✓ Slack notification sent")
                return True
            else:
                print(f"WARNING: Slack returned {response.status_code}: {response.text}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"WARNING: Slack notification failed: {e}", file=sys.stderr)
        return False


# ─── Telegram Notifications ──────────────────────────────

def notify_telegram(message, data=None, bot_token=None, chat_id=None):
    """
    Send a plain-text notification to Telegram.
    Used for system alerts and status updates — NOT for interactive flows.
    For interactive flows (buttons, await_text), use telegram_bot.py directly.
    """
    bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Skipping Telegram notification.", file=sys.stderr)
        return False

    if httpx is None:
        print("WARNING: httpx not installed. Skipping Telegram notification.", file=sys.stderr)
        return False

    # Build text: append structured data if provided
    text = message
    if data and isinstance(data, dict):
        data_lines = "\n".join(f"• *{k}:* {v}" for k, v in data.items())
        text = f"{message}\n\n{data_lines}"

    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(url, json=payload)
            if response.status_code == 200:
                print("✓ Telegram notification sent")
                return True
            else:
                print(f"WARNING: Telegram returned {response.status_code}: {response.text}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"WARNING: Telegram notification failed: {e}", file=sys.stderr)
        return False


# ─── Unified Notify ───────────────────────────────────────

def notify(message, data=None, channel="both", level="info"):
    """
    Send notification to specified channel(s).
    channel: "terminal", "slack", "telegram", "all", "both" (terminal+slack, legacy)
    """
    if channel in ("terminal", "both", "all"):
        notify_terminal(message, data, level)
    if channel in ("slack", "both", "all"):
        notify_slack(message, data)
    if channel in ("telegram", "all"):
        notify_telegram(message, data)


# ─── Pre-built Notification Templates ─────────────────────

def notify_task_created(task_name, task_url, summary, channel="both"):
    """Notification for when a new ClickUp task is created."""
    notify(
        f"Created new task: *{task_name}*",
        data={"Summary": summary, "URL": task_url, "Action": "Created"},
        channel=channel,
        level="success",
    )


def notify_task_updated(task_name, task_url, new_status, summary, channel="both"):
    """Notification for when an existing task is updated."""
    notify(
        f"Updated task: *{task_name}* → {new_status}",
        data={"Summary": summary, "URL": task_url, "Status": new_status, "Action": "Updated"},
        channel=channel,
        level="success",
    )


def notify_comment_added(task_name, task_url, comment_preview, channel="both"):
    """Notification for when a comment is added to a task."""
    notify(
        f"Comment added to: *{task_name}*",
        data={"Comment": comment_preview[:100], "URL": task_url, "Action": "Commented"},
        channel=channel,
        level="info",
    )


def notify_skipped(reason, channel="both"):
    """Notification for when sync is skipped."""
    notify(
        f"Sync skipped: {reason}",
        channel=channel,
        level="warning",
    )


# ─── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Notification Helper")
    parser.add_argument("--message", help="Notification message text")
    parser.add_argument("--json", help="Structured data as JSON string")
    parser.add_argument("--channel", choices=["terminal", "slack", "telegram", "both", "all"], default="both",
                        help="Where to send the notification (both=terminal+slack, all=terminal+slack+telegram)")
    parser.add_argument("--level", choices=["info", "success", "warning", "error"], default="info",
                        help="Notification level")

    args = parser.parse_args()

    if not args.message and not args.json:
        parser.error("Provide --message or --json")

    data = None
    if args.json:
        try:
            data = json.loads(args.json)
        except json.JSONDecodeError:
            print("ERROR: Invalid JSON in --json argument", file=sys.stderr)
            sys.exit(1)

    message = args.message or json.dumps(data, indent=2)
    notify(message, data, args.channel, args.level)


if __name__ == "__main__":
    main()
