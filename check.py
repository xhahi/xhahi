"""Run:  python check.py   -> tests each step and says what is wrong."""
from main import compute_events, fmt, get_candles, load_config
from gold_alerts.strategy import IST, ema, in_window
from gold_alerts.telegram import Telegram

cfg = load_config()


def step(n, text):
    print(f"\n[{n}] {text}")


step(1, "Config keys")
need = ["telegram_bot_token", "telegram_chat_id"]
if cfg["data_provider"] == "oanda":
    need.append("oanda_token")
elif cfg["data_provider"] == "twelvedata":
    need.append("twelvedata_api_key")
else:
    print("  XAUS: no API key required")
for k in need:
    print(f"  {k}: {'ok' if cfg.get(k) else 'MISSING (config.json or environment variable)'}")

step(2, "Telegram")
tg = Telegram(cfg["telegram_bot_token"], cfg["telegram_chat_id"])
try:
    tg.send("Test message from check.py - Telegram works.")
    print("  OK: check your Telegram.")
except Exception as e:
    print(f"  FAILED: {e}\n  -> wrong token/chat id, or you never sent a message to your bot.")

step(3, f"Price data ({cfg['data_provider']}, XAU/USD M15)")
try:
    m15 = get_candles(cfg)
    print(f"  OK: {len(m15)} candles, last closed: {m15[-1].end.astimezone(IST):%d %b %H:%M} IST")
except Exception as e:
    print(f"  FAILED: {e}\n  -> check the selected data provider and internet connection.")
    raise SystemExit

step(4, "Latest events found")
events = compute_events(cfg, m15)
for e in events[-8:]:
    inw = in_window(e.time, *cfg["window_ist"])
    print(f"  {e.time.astimezone(IST):%d %b %H:%M} IST {e.kind:10} "
          f"{'UP' if e.dir == 1 else 'DOWN':4} {'in window' if inw else 'outside window'}")
if events:
    try:
        tg.send("SAMPLE (past event):\n" + fmt(events[-1], m15[-1].c,
                ema([b.c for b in m15], cfg["ema_length"]), cfg))
        print("  Sample alert sent to Telegram.")
    except Exception as e:
        print(f"  sample failed: {e}")
