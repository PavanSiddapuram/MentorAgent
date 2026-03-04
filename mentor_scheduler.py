"""
MentorAgent Scheduler
----------------------
Runs the full daily accountability loop using APScheduler.
Triggers 7 AM morning flow and 9 PM evening accountability check.
Also fires a weekly summary every Sunday at 10 PM.

The scheduler calls deterministic scripts for data and messaging.
All ADAPTIVE REASONING (difficulty scaling, message composition, escalation)
is handled by the Copilot orchestrator or an LLM call (standalone mode).

Usage:
    # Run persistently (keep terminal open or use nohup/pm2/Modal)
    python execution/mentor_scheduler.py

    # Test a single flow immediately (skip scheduler)
    python execution/mentor_scheduler.py --test morning
    python execution/mentor_scheduler.py --test evening
    python execution/mentor_scheduler.py --test weekly

Environment variables:
    MORNING_HOUR        - default: 7
    MORNING_MINUTE      - default: 0
    EVENING_HOUR        - default: 21
    EVENING_MINUTE      - default: 0
    TIMEZONE            - default: America/New_York
    GOOGLE_SHEET_ID     - 90_Day_Master_Plan sheet ID
    TELEGRAM_BOT_TOKEN  - Bot token
    TELEGRAM_CHAT_ID    - Your chat ID
"""

import os
import sys
import json
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path
from dotenv import load_dotenv

from telegram_bot import TelegramBot
from gcal_events import create_study_event, infer_color
from github_verifier import verify_commit
from read_sheet import read_google_sheet

load_dotenv(Path(__file__).resolve().parent / ".env")

# ── Sheet adapter helpers ─────────────────────────────────────────────────────
# read_sheet.py and update_sheet.py were built for lead-gen workflows.
# These thin wrappers adapt them for the MentorAgent use case.

def read_sheet_to_json(sheet_id: str, sheet_name: str) -> list[dict]:
    """Pull all rows from the named worksheet as a list of dicts."""
    rows = read_google_sheet(sheet_url=sheet_id, worksheet_name=sheet_name)
    return rows if rows is not None else []


def update_sheet_from_json(sheet_data: list[dict], sheet_id: str, sheet_name: str) -> None:
    """
    Write updated sheet_data (list of dicts) back to the named worksheet.
    Uses gspread directly — avoids the file-based update_sheet.py which targets lead exports.
    """
    import json
    import gspread
    from read_sheet import get_credentials  # reuse OAuth flow from read_sheet

    try:
        creds = get_credentials()
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)

        if not sheet_data:
            return

        headers = list(sheet_data[0].keys())
        rows = [headers] + [[str(row.get(h, "")) for h in headers] for row in sheet_data]

        # Resize if needed
        if len(rows) > worksheet.row_count or len(headers) > worksheet.col_count:
            worksheet.resize(rows=max(len(rows), worksheet.row_count),
                             cols=max(len(headers), worksheet.col_count))

        worksheet.update(values=rows, value_input_option="USER_ENTERED")
        print(f"[Sheet] Updated {len(sheet_data)} rows in '{sheet_name}'")
    except Exception as e:
        print(f"[Sheet] update_sheet_from_json error: {e}", file=sys.stderr)

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    print("APScheduler not installed. Run: pip install apscheduler")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────────────

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")
MORNING_HOUR = int(os.getenv("MORNING_HOUR", 7))
MORNING_MINUTE = int(os.getenv("MORNING_MINUTE", 0))
EVENING_HOUR = int(os.getenv("EVENING_HOUR", 21))
EVENING_MINUTE = int(os.getenv("EVENING_MINUTE", 0))

# ── Sheet helpers ────────────────────────────────────────────────────────────

def get_today_row(sheet_data: list[dict], meta: dict = None) -> dict | None:
    """
    Find today's task row using the start_date stored in the meta tab.

    If meta contains 'start_date' (YYYY-MM-DD), computes the target day number
    as (today - start_date).days + 1 and returns that specific row.

    Falls back to the lowest-numbered Pending row if start_date is not set
    (backwards-compatible with existing deployments).
    """
    if meta:
        start_date_str = meta.get("start_date", "").strip()
        if start_date_str:
            try:
                from datetime import date
                start_dt = date.fromisoformat(start_date_str)
                target_day = (date.today() - start_dt).days + 1
                # Find the row matching target_day exactly
                for row in sheet_data:
                    if int(row.get("Day", -1)) == target_day:
                        return row if row.get("Status", "").strip() == "Pending" else None
                return None  # target day not found or already completed
            except (ValueError, TypeError):
                pass  # fall through to legacy behaviour

    # Legacy: return the first pending row (lowest Day number)
    pending = [r for r in sheet_data if r.get("Status", "").strip() == "Pending"]
    if not pending:
        return None
    return min(pending, key=lambda r: int(r.get("Day", 999)))


def get_meta(meta_rows: list[dict]) -> dict:
    """
    Parse meta values from the 'meta' tab.
    Expects rows with 'Key' and 'Value' columns:
        Key               | Value
        ------------------|-------
        current_streak    | 7
        last_completed_day| 42
        consecutive_missed| 0
    """
    meta = {
        "current_streak": 0,
        "last_completed_day": 0,
        "consecutive_missed": 0,
    }
    for row in meta_rows:
        key = row.get("Key", "").strip()
        val = row.get("Value", "")
        if key in meta:
            try:
                meta[key] = int(val)
            except (ValueError, TypeError):
                pass
    return meta


def update_meta_tab(sheet_id: str, updates: dict) -> None:
    """
    Update key-value pairs in the 'meta' tab.

    Args:
        sheet_id: Google Sheet ID
        updates: dict of {key: new_value} pairs to write, e.g.
                 {"current_streak": 5, "consecutive_missed": 0}
    """
    meta_rows = read_sheet_to_json(sheet_id=sheet_id, sheet_name="meta")
    for row in meta_rows:
        key = row.get("Key", "").strip()
        if key in updates:
            row["Value"] = str(updates[key])
    update_sheet_from_json(meta_rows, sheet_id=sheet_id, sheet_name="meta")
    print(f"[Meta] Updated: {updates}")


def update_row_in_sheet(sheet_data: list[dict], day: int, updates: dict) -> list[dict]:
    """Apply field updates to the row with matching Day number."""
    for row in sheet_data:
        if int(row.get("Day", -1)) == day:
            row.update(updates)
    return sheet_data


# ── Core flow helpers ─────────────────────────────────────────────────────────

def compose_morning_message(row: dict, meta: dict) -> str:
    """Build the morning Telegram message from the sheet row and meta."""
    week = row.get("Week", "?")
    phase = row.get("Phase", "")
    core_task = row.get("Core Task", "(no task found)")
    reading = row.get("Secondary Reading", "")
    reflection = row.get("Reflection Prompt", "")
    difficulty = int(row.get("Difficulty Level", 3))
    layer = row.get("Layer", "")
    artifact = row.get("Artifact Produced", "")
    streak = meta.get("current_streak", 0)
    consecutive_missed = meta.get("consecutive_missed", 0)

    # Adaptive adjustments (deterministic part — orchestrator handles nuance)
    if consecutive_missed >= 2:
        core_task = f"[REDUCED SCOPE] {core_task}\n_(Focus on the 30-min minimum viable version only.)_"

    difficulty_bar = "⬛" * difficulty + "⬜" * (5 - difficulty)

    parts = [
        f"<b>Good morning.</b>",
        f"Week {week} — {phase}",
    ]
    if layer:
        parts.append(f"Layer: <code>{layer}</code>")
    parts += [
        "",
        f"<b>Core Task:</b>",
        core_task,
    ]
    if artifact:
        parts += ["", f"<b>🎯 Expected Artifact:</b>", f"<i>{artifact}</i>"]
    if reading:
        # Format paper/resource links as clickable hyperlinks
        links = [link.strip() for link in reading.split("|") if link.strip()]
        formatted_links = []
        for link in links:
            if "arxiv.org" in link:
                # Extract arxiv paper ID for label
                paper_id = link.rstrip("/").split("/")[-1]
                formatted_links.append(f'📄 <a href="{link}">arXiv:{paper_id}</a>')
            elif "github.com" in link or "github.io" in link:
                formatted_links.append(f'💻 <a href="{link}">{link.split("//")[1][:40]}</a>')
            else:
                # Generic resource
                domain = link.split("//")[1].split("/")[0] if "//" in link else link[:40]
                formatted_links.append(f'📖 <a href="{link}">{domain}</a>')
        parts += ["", "<b>Reading / Papers:</b>"] + formatted_links
    if reflection:
        parts += ["", f"<b>Think About:</b>", f"<i>{reflection}</i>"]

    parts += [
        "",
        f"Difficulty: {difficulty_bar} ({difficulty}/5)",
        f"Streak: 🔥 {streak} days",
    ]
    return "\n".join(parts)


def run_morning_flow():
    """
    Morning flow — triggered at 7 AM.
    1. Pull today's row from Sheet
    2. Compose morning message (with adaptive logic)
    3. Create Google Calendar event
    4. Send Telegram message
    """
    print(f"\n[{datetime.now().isoformat()}] ── MORNING FLOW ──")
    bot = TelegramBot()

    # Bootstrap credentials with ALL scopes (Sheets + Drive + Calendar)
    # Must happen before read_sheet_to_json which saves a narrower token
    from gcal_events import get_credentials as gcal_get_credentials
    gcal_get_credentials()

    try:
        # 1. Pull Sheet data
        sheet_data = read_sheet_to_json(sheet_id=SHEET_ID, sheet_name="90_Day_Master_Plan")
        today_row = get_today_row(sheet_data)

        if not today_row:
            bot.send(
                "⚠️ MentorAgent: No pending tasks found in the Sheet. "
                "Please populate the next rows before tomorrow."
            )
            print("[Morning] No pending rows found.")
            return

        meta_rows = read_sheet_to_json(sheet_id=SHEET_ID, sheet_name="meta")
        meta = get_meta(meta_rows)

        # 2. Compose message
        message = compose_morning_message(today_row, meta)

        # 3. Create Calendar event (non-blocking — errors logged, not raised)
        topic = today_row.get("Topic", today_row.get("Core Task", "AI Sprint"))
        color = infer_color(topic)
        today_str = date.today().isoformat()
        create_study_event(
            title=f"AI Sprint – {topic}",
            date=today_str,
            start_time="09:00",
            duration_minutes=60,
            color=color,
            description=f"Core Task: {today_row.get('Core Task', '')}\n\n"
                        f"Reading: {today_row.get('Secondary Reading', '')}",
        )

        # 4. Send Telegram
        bot.send(message, parse_mode="HTML")
        print(f"[Morning] Sent morning message for Day {today_row.get('Day')}")

    except Exception as e:
        print(f"[Morning] ERROR: {e}")
        try:
            bot.send(f"⚠️ MentorAgent morning flow error: {e}")
        except Exception:
            pass


def run_evening_flow():
    """
    Evening flow — triggered at 9 PM.
    1. Ask completion status via Telegram buttons
    2. Follow up based on response
    3. Update Sheet
    """
    print(f"\n[{datetime.now().isoformat()}] ── EVENING FLOW ──")
    bot = TelegramBot()

    try:
        sheet_data = read_sheet_to_json(sheet_id=SHEET_ID, sheet_name="90_Day_Master_Plan")
        today_row = get_today_row(sheet_data)

        if not today_row:
            print("[Evening] No pending row found — skipping evening check.")
            return

        day = int(today_row.get("Day", 0))
        meta_rows = read_sheet_to_json(sheet_id=SHEET_ID, sheet_name="meta")
        meta = get_meta(meta_rows)

        # 1. Ask completion status
        response = bot.ask_buttons(
            text="Did you complete today's core task?",
            buttons=["✅ Completed", "⚠️ Partial", "❌ Missed"],
            timeout=1800,  # 30 min
        )

        if response is None:
            bot.send("No response received. Logging today as Partial. Update the sheet manually if needed.")
            updates = {"Status": "Partial", "Notes": "No evening response"}
            update_row_in_sheet(sheet_data, day, updates)
            update_sheet_from_json(sheet_data, sheet_id=SHEET_ID, sheet_name="90_Day_Master_Plan")
            return

        # ── Completed ─────────────────────────────────────────────────────────
        if "Completed" in response:
            commit_text = bot.ask_text(
                "Paste your commit link (or type 'no commit' if non-code task):",
                timeout=300,
            )

            commit_status = ""
            notes = ""

            if commit_text and commit_text.lower() not in ["no commit", "skip", "none", "-"]:
                result = verify_commit(commit_text)
                if result["valid"]:
                    bot.send(result["display"])
                    commit_status = result["url"]
                else:
                    bot.send(f"⚠️ Could not verify commit: {result['error']}\nLogging as unverified.")
                    commit_status = f"unverified: {commit_text}"
            else:
                commit_status = "no-commit"

            # ── Collect engineering signals ────────────────────────────────
            artifact_text = bot.ask_text(
                "What artifact did you produce today? (e.g. 'benchmark script', 'API module', 'dashboard')",
                timeout=300,
            )
            artifact_produced = artifact_text if artifact_text and artifact_text.lower() not in ["skip", "-"] else ""

            metric = bot.ask_text(
                "Key metric improved? (e.g. 'MRR@10: 0.41→0.63' or 'skip')",
                timeout=300,
            )
            measured_metric = metric if metric and metric.lower() not in ["skip", "-"] else ""

            failure_text = bot.ask_text(
                "Failure mode discovered? (e.g. 'OOM at 500k docs' or 'skip')",
                timeout=300,
            )
            failure_mode = failure_text if failure_text and failure_text.lower() not in ["skip", "-"] else ""

            tradeoff_text = bot.ask_text(
                "Tradeoff identified? (e.g. 'reranker +12% NDCG but 2x latency' or 'skip')",
                timeout=300,
            )
            tradeoff = tradeoff_text if tradeoff_text and tradeoff_text.lower() not in ["skip", "-"] else ""

            reuse_text = bot.ask_text(
                "Reusability score 1-5? (1=demo-only, 5=production-grade, or 'skip')",
                timeout=180,
            )
            reusability = ""
            if reuse_text and reuse_text.strip() in ["1", "2", "3", "4", "5"]:
                reusability = reuse_text.strip()

            paper_text = bot.ask_text(
                "Did you read the linked paper? (yes/no)",
                timeout=120,
            )
            paper_read = ""
            key_insight = ""
            if paper_text and paper_text.lower().startswith("y"):
                paper_read = "Yes"
                insight = bot.ask_text(
                    "Key insight from the paper? (1 sentence)",
                    timeout=300,
                )
                key_insight = insight if insight and insight.lower() not in ["skip", "-"] else ""
            elif paper_text:
                paper_read = "No"

            # ── Warn on missing signals (don't block) ─────────────────────
            missing = []
            if not artifact_produced:
                missing.append("Artifact")
            if not measured_metric:
                missing.append("Metric")
            if not failure_mode:
                missing.append("Failure Mode")
            if missing:
                bot.send(f"⚠️ Missing: {', '.join(missing)}\n(Consider filling these for stronger signal.)")

            notes = measured_metric or ""

            # Update streak
            new_streak = meta.get("current_streak", 0) + 1
            updates = {
                "Status": "Done",
                "Commit Link": commit_status,
                "Notes": notes,
                "Streak": new_streak,
                "Artifact Produced": artifact_produced,
                "Measured Metric": measured_metric,
                "Failure Mode Found": failure_mode,
                "Tradeoff Identified": tradeoff,
                "Reusability Score": reusability,
                "Paper Read": paper_read,
                "Key Insight": key_insight,
            }
            update_row_in_sheet(sheet_data, day, updates)
            update_sheet_from_json(sheet_data, sheet_id=SHEET_ID, sheet_name="90_Day_Master_Plan")
            update_meta_tab(SHEET_ID, {
                "current_streak": new_streak,
                "consecutive_missed": 0,
                "last_completed_day": day,
            })

            bot.send(f"Day {day} locked in. Streak: 🔥{new_streak}")
            print(f"[Evening] Day {day} completed. Streak: {new_streak}")

        # ── Partial ──────────────────────────────────────────────────────────
        elif "Partial" in response:
            reason = bot.ask_text(
                "What did you get done? What blocked you? (or 'skip')",
                timeout=300,
            )
            updates = {"Status": "Partial", "Notes": reason or "partial — no details"}
            update_row_in_sheet(sheet_data, day, updates)
            update_sheet_from_json(sheet_data, sheet_id=SHEET_ID, sheet_name="90_Day_Master_Plan")
            bot.send("Partial logged. Tomorrow, finish the core task first before the new one.")
            print(f"[Evening] Day {day} partial.")

        # ── Missed ───────────────────────────────────────────────────────────
        elif "Missed" in response:
            reason = bot.ask_text("What happened? (optional — or 'skip')", timeout=180)
            consecutive_missed = meta.get("consecutive_missed", 0) + 1
            updates = {
                "Status": "Missed",
                "Notes": reason or "missed — no reason given",
                "Streak": 0 if consecutive_missed >= 2 else meta.get("current_streak", 0),
            }
            update_row_in_sheet(sheet_data, day, updates)
            update_sheet_from_json(sheet_data, sheet_id=SHEET_ID, sheet_name="90_Day_Master_Plan")
            update_meta_tab(SHEET_ID, {
                "consecutive_missed": consecutive_missed,
                "current_streak": 0 if consecutive_missed >= 2 else meta.get("current_streak", 0),
            })

            if consecutive_missed >= 2:
                bot.send(
                    f"You are drifting from your 90-day target.\n\n"
                    f"Days missed: {consecutive_missed}\n"
                    f"Current streak: 0\n\n"
                    f"Tomorrow's task will be reduced to its 30-minute minimum.\n\n"
                    f"No guilt. Just ship something."
                )
            else:
                bot.send("One miss. Tomorrow's difficulty will be adjusted down slightly.")
            print(f"[Evening] Day {day} missed. Consecutive missed: {consecutive_missed}")

    except Exception as e:
        print(f"[Evening] ERROR: {e}")
        try:
            bot.send(f"⚠️ MentorAgent evening flow error: {e}")
        except Exception:
            pass


def run_weekly_summary():
    """
    Weekly summary — every Sunday 10 PM.
    Reads the last 7 rows, computes completion rate, sends summary via Telegram.
    """
    print(f"\n[{datetime.now().isoformat()}] ── WEEKLY SUMMARY ──")
    bot = TelegramBot()

    try:
        sheet_data = read_sheet_to_json(sheet_id=SHEET_ID, sheet_name="90_Day_Master_Plan")

        # Find the most recently completed week
        done_rows = [r for r in sheet_data if r.get("Status") in ("Done", "Partial", "Missed")]
        if not done_rows:
            bot.send("No completed days yet — weekly summary skipped.")
            return

        # Group last 7 completed/attempted rows
        last_7 = sorted(done_rows, key=lambda r: int(r.get("Day", 0)))[-7:]
        week_num = last_7[-1].get("Week", "?")
        done_count = sum(1 for r in last_7 if r.get("Status") == "Done")
        total = len(last_7)
        pct = round(done_count / total * 100)

        wins = [
            f"• Day {r.get('Day')}: {r.get('Notes', '')}"
            for r in last_7
            if r.get("Status") == "Done" and r.get("Notes")
        ]
        wins_text = "\n".join(wins) if wins else "• Keep shipping."

        # Peek next week theme
        next_pending = [r for r in sheet_data if r.get("Status") == "Pending"]
        next_week_theme = next_pending[0].get("Phase", "") if next_pending else "Stay consistent."

        streak = max(int(r.get("Streak", 0)) for r in last_7)

        # Check if any paper was read this week
        papers_read = sum(1 for r in last_7 if r.get("Paper Read", "").strip().lower() == "yes")
        paper_line = ""
        if papers_read == 0:
            paper_line = "\n📖 <b>No paper read this week</b> — consider summarizing one before next week."
        else:
            paper_line = f"\n📖 Papers read: {papers_read}/{total}"

        # Layer coverage analysis
        layers_hit = set(r.get("Layer", "") for r in last_7 if r.get("Status") == "Done" and r.get("Layer"))
        layer_line = f"Layers covered: {', '.join(sorted(layers_hit))}" if layers_hit else ""

        message = (
            f"<b>Week {week_num} Complete.</b>\n\n"
            f"Completion: {done_count}/{total} days ({pct}%)\n"
            f"Streak: 🔥{streak}\n"
            f"{layer_line}\n"
            f"{paper_line}\n\n"
            f"<b>Wins this week:</b>\n{wins_text}\n\n"
            f"<b>Next week:</b> {next_week_theme}"
        )
        bot.send(message, parse_mode="HTML")
        print(f"[Weekly] Summary sent for Week {week_num}: {done_count}/{total}")

    except Exception as e:
        print(f"[Weekly] ERROR: {e}")
        try:
            bot.send(f"⚠️ MentorAgent weekly summary error: {e}")
        except Exception:
            pass


# ── Scheduler entry point ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MentorAgent Scheduler")
    parser.add_argument(
        "--test",
        choices=["morning", "evening", "weekly"],
        help="Run a single flow immediately (bypass scheduler)",
    )
    args = parser.parse_args()

    if args.test == "morning":
        run_morning_flow()
    elif args.test == "evening":
        run_evening_flow()
    elif args.test == "weekly":
        run_weekly_summary()
    else:
        print("Starting MentorAgent Scheduler...")
        print(f"  Morning: {MORNING_HOUR:02d}:{MORNING_MINUTE:02d}")
        print(f"  Evening: {EVENING_HOUR:02d}:{EVENING_MINUTE:02d}")
        print(f"  Weekly:  Sunday 22:00")
        print(f"  Timezone: {TIMEZONE}")
        print("  Press Ctrl+C to stop.\n")

        scheduler = BlockingScheduler(timezone=TIMEZONE)

        scheduler.add_job(
            run_morning_flow,
            CronTrigger(hour=MORNING_HOUR, minute=MORNING_MINUTE, timezone=TIMEZONE),
            id="morning",
            name="Morning Directive",
            misfire_grace_time=300,  # 5 min grace window
        )
        scheduler.add_job(
            run_evening_flow,
            CronTrigger(hour=EVENING_HOUR, minute=EVENING_MINUTE, timezone=TIMEZONE),
            id="evening",
            name="Evening Accountability",
            misfire_grace_time=300,
        )
        scheduler.add_job(
            run_weekly_summary,
            CronTrigger(day_of_week="sun", hour=22, minute=0, timezone=TIMEZONE),
            id="weekly",
            name="Weekly Summary",
            misfire_grace_time=600,
        )

        try:
            scheduler.start()
        except KeyboardInterrupt:
            print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
