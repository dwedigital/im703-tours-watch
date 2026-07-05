"""IRONMAN 70.3 Tours registration watcher — Render cron job.

Fetches the register page, and when registration opens (or the page changes
materially) sends a Telegram DM via the Bot API.

Env vars (set in Render, never committed):
  TELEGRAM_BOT_TOKEN  — Telegram bot token
  TELEGRAM_CHAT_ID    — chat to alert
  RENDER_API_KEY      — optional; if set with SERVICE_ID, suspends this cron
                        job after the first alert so it doesn't repeat
  SERVICE_ID          — optional; this cron job's Render service id
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# Once an alert has fired, this file stops every later run from re-alerting
# (the cron keeps firing; runs become no-ops). Delete it to re-arm the watcher.
STATE_FILE = Path(__file__).resolve().parent / "ALERTED"

URL = "https://www.ironman.com/races/im703-tours/register"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Closed wordings seen so far (matched against tag-stripped text, since the
# sentence can be split across HTML elements):
#   2026-07-02: "General Registration ... will open soon."
#   2026-07-04: "General Registration ... will open on 09 July 2027 at 2:00 PM CEST !"
#               (sic — CMS says 2027; presumably means 2026)
CLOSED_MARKER = re.compile(r"General Registration.{0,200}?will open (soon|on)", re.IGNORECASE)

# When Ironman opens registration they add a checkout CTA pointing at the
# competitor.com/ironman registration platform.
OPEN_CTA = re.compile(
    r'href="https?://[^"]*(competitor\.(ironman|labs)?|labs-v2\.competitor|endurancecue|register\.ironman)[^"]*"',
    re.IGNORECASE,
)


def fetch(url: str) -> str:
    """Browser-impersonating fetch (Cloudflare rejects vanilla Python TLS)."""
    try:
        from curl_cffi import requests as cffi_requests

        resp = cffi_requests.get(url, impersonate="chrome131", timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        print(f"curl_cffi fetch failed ({exc}); falling back to system curl", file=sys.stderr)
        result = subprocess.run(
            ["curl", "-sL", "--fail", "--max-time", "30", "-A", UA, url],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl failed (exit {result.returncode}): {result.stderr.strip()}")
        return result.stdout


def telegram(message: str) -> None:
    from curl_cffi import requests as cffi_requests

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    resp = cffi_requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message},
        timeout=30,
    )
    resp.raise_for_status()
    print("Telegram alert sent")


def suspend_self() -> None:
    """Best-effort: stop this cron job after alerting so it doesn't repeat."""
    api_key = os.environ.get("RENDER_API_KEY")
    service_id = os.environ.get("SERVICE_ID")
    if not (api_key and service_id):
        print("No RENDER_API_KEY/SERVICE_ID — job will keep alerting until suspended manually")
        return
    from curl_cffi import requests as cffi_requests

    resp = cffi_requests.post(
        f"https://api.render.com/v1/services/{service_id}/suspend",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    print(f"Self-suspend: HTTP {resp.status_code}")


def main() -> int:
    if STATE_FILE.exists():
        print("Already alerted (ALERTED file present) — skipping. Delete it to re-arm.")
        return 0

    html = fetch(URL)

    if len(html) < 10000 or "cf-browser-verification" in html or "Just a moment" in html:
        # Cloudflare challenge page, not real content — don't misread as CHANGED
        raise RuntimeError(f"Fetch likely blocked by Cloudflare (got {len(html)} bytes)")

    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    closed_text = bool(CLOSED_MARKER.search(text))
    cta = OPEN_CTA.search(html)

    if cta:
        link = cta.group(0)[6:-1]
        print(f"OPEN — registration link found: {link}")
        telegram(
            "🏊🚴🏃 IRONMAN 70.3 Tours registration is OPEN!\n"
            f"Register: {URL}\n"
            f"Checkout link found: {link}"
        )
        STATE_FILE.touch()
        suspend_self()
        return 0
    if not closed_text:
        print("CHANGED — 'will open soon' text is gone but no register link yet.")
        telegram(
            "⚠️ IRONMAN 70.3 Tours register page changed — 'will open soon' text is gone. "
            f"Check it now: {URL}"
        )
        STATE_FILE.touch()
        suspend_self()
        return 0
    print("CLOSED — page still says registration will open soon.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
