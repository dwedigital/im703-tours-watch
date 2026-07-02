# IM 70.3 Tours registration watch

Render cron job (every 2 min) that checks
https://www.ironman.com/races/im703-tours/register and sends a Telegram DM
the moment registration opens. Uses curl_cffi (Chrome TLS impersonation) to
get past Cloudflare. Secrets live in Render env vars, not this repo.

Local run: TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python check.py
