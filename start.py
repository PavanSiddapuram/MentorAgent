"""
Railway/Cloud Startup Script
-----------------------------
Decodes Google credentials from environment variables (base64-encoded)
and then starts the scheduler.

In Railway dashboard, set:
    GOOGLE_CREDENTIALS_B64  = base64-encoded contents of credentials.json
    GOOGLE_TOKEN_B64        = base64-encoded contents of token.json

All other env vars (TELEGRAM_BOT_TOKEN, GOOGLE_SHEET_ID, etc.) are set
directly in Railway dashboard — they override anything in .env.
"""

import os
import sys
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def decode_secrets():
    """Write credentials.json and token.json from base64 env vars."""
    creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
    token_b64 = os.getenv("GOOGLE_TOKEN_B64")

    if creds_b64:
        creds_path = ROOT / "credentials.json"
        creds_path.write_bytes(base64.b64decode(creds_b64))
        print("[Startup] Wrote credentials.json from GOOGLE_CREDENTIALS_B64")
    else:
        if not (ROOT / "credentials.json").exists():
            print("[Startup] WARNING: No GOOGLE_CREDENTIALS_B64 and no credentials.json found!")

    if token_b64:
        token_path = ROOT / "token.json"
        token_path.write_bytes(base64.b64decode(token_b64))
        print("[Startup] Wrote token.json from GOOGLE_TOKEN_B64")
    else:
        if not (ROOT / "token.json").exists():
            print("[Startup] WARNING: No GOOGLE_TOKEN_B64 and no token.json found!")


def main():
    print("[Startup] MentorAgent cloud deployment starting...")
    decode_secrets()

    # Import and run the scheduler (blocking — keeps the container alive)
    from mentor_scheduler import main as scheduler_main
    sys.argv = [sys.argv[0]]  # Clear any Docker CMD args
    scheduler_main()


if __name__ == "__main__":
    main()
