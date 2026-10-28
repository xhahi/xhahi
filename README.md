# XAU/USD M15 Telegram line-break alerts (Twelve Data candles)

This version uses Twelve Data M15 OHLC candles instead of XAUS sampled spot prices. It is configured for M15 line-break alerts only; H4 BO, OP, and CF are OFF. You need a Twelve Data API key, and access/limits for XAU/USD intraday data depend on the provider's current plan. The feed may still differ from your chart's broker feed, so compare candles before relying on alerts.

Get an API key at https://twelvedata.com/ and paste it into `twelvedata_api_key` in `config.json`. Do not share the key publicly.

## 1. Telegram setup
1. In Telegram, message `@BotFather` and run `/newbot`. Copy the bot token.
2. Send a message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy your chat ID from `message.chat.id`.
4. Put `telegram_bot_token` and `telegram_chat_id` in `config.json`, or use environment variables `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Keep these secret.

## 2. Run locally
Install Python 3.10+ and run:

```bash
pip install -r requirements.txt
python check.py
python main.py
```

`check.py` sends a Telegram test message and checks the price feed. `main.py` runs continuously.

## 3. Run with GitHub Actions
1. Upload the contents of this folder to a GitHub repository (include `.github`).
2. In **Settings → Secrets and variables → Actions**, add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Run the `gold-alerts` workflow once from the Actions tab. The scheduled workflow checks about every 5 minutes, but GitHub may delay scheduled starts.

## Commands
`/status` · `/off` · `/on` · `/m15 on` · `/m15 off`

## Settings
- `window_ist`: alert window in India time, currently `10:30`–`23:59`.
- `swing_length_lower`: number of closes used to confirm swing levels.
- `mode`: `m15_breaks` for M15 line-break alerts, or `h4_cycle` for H4 breakout → opposite break → confirmation.

The XAUS feed is an indicative reference price, not a tradable broker quote.
