"""
Generates Railway environment variable values.
Run locally, then copy-paste the output into Railway dashboard.
NEVER commit this output to git.
"""
import base64
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(r"c:\Users\Sidda\OneDrive\Desktop\Projects\Agents\MentorAgent")
load_dotenv(ROOT / ".env")

print("=" * 60)
print("RAILWAY ENVIRONMENT VARIABLES")
print("Copy each key=value pair into Railway dashboard > Variables")
print("=" * 60)
print()

# Direct env vars
for key in [
    "GOOGLE_SHEET_ID",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GITHUB_TOKEN",
    "GITHUB_REPO",
    "TIMEZONE",
    "MORNING_HOUR",
    "EVENING_HOUR",
    "CALENDAR_ID",
]:
    val = os.getenv(key, "")
    if val:
        print(f"{key}={val}")

print()

# Base64-encoded credential files
creds_path = ROOT / "credentials.json"
token_path = ROOT / "token.json"

if creds_path.exists():
    b64 = base64.b64encode(creds_path.read_bytes()).decode()
    print(f"GOOGLE_CREDENTIALS_B64={b64}")
    print()

if token_path.exists():
    b64 = base64.b64encode(token_path.read_bytes()).decode()
    print(f"GOOGLE_TOKEN_B64={b64}")

print()
print("=" * 60)
print("Done! Set all variables above in Railway dashboard.")
print("=" * 60)
