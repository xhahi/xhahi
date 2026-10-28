"""XAU/USD Telegram alert bot.

  python main.py          run forever (own server / PC)
  python main.py --once   check once and exit (for GitHub Actions)
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gold_alerts.data import fetch_m15, fetch_oanda_m15, fetch_xaus_m15, resample
from gold_alerts.strategy import Event, IST, ema, in_window, line_breaks, run_cycle
from gold_alerts.telegram import Telegram

UTC = timezone.utc
BASE = Path(__file__).parent
STATE_FILE = BASE / "state.json"
LOWER = {"M15": 15, "M30": 30, "H1": 60}
KEYS = {"/m15": "m15", "/h4bo": "h4_bo", "/op": "op", "/cf": "cf"}
KIND_KEY = {"M15_BREAK": "m15", "H4_BO": "h4_bo", "OP": "op", "CF": "cf"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("bot")

DEFAULTS = {
    "mode": "m15_breaks", "data_provider": "xaus", "symbol": "XAU/USD",
    "oanda_instrument": "XAU_USD", "oanda_env": "practice", "candles_count": 1500,
    "swing_length_h4": 2, "swing_length_lower": 2,
    "lower_timeframes": ["M15", "M30", "H1"],
    "h4_anchor_tz": "America/New_York", "h4_anchor_hour": 17,
    "window_ist": ["10:30", "23:59"],
    "alerts": {"m15": True, "h4_bo": True, "op": True, "cf": True},
    "ema_length": 50, "poll_delay_sec": 15, "max_alert_age_min": 45,
}


def load_config():
    cfg = dict(DEFAULTS)
    cfg.update(json.loads((BASE / "config.json").read_text()))
    for k, env in (("twelvedata_api_key", "TWELVEDATA_API_KEY"),
                   ("oanda_token", "OANDA_TOKEN"),
                   ("telegram_bot_token", "TELEGRAM_BOT_TOKEN"),
                   ("telegram_chat_id", "TELEGRAM_CHAT_ID")):
        cfg[k] = os.environ.get(env) or cfg.get(k, "")
    return cfg


def load_state(cfg):
    if STATE_FILE.exists():
        s = json.loads(STATE_FILE.read_text())
    else:
        s = {"initialized": False, "sent": [], "tg_offset": 0}
    s.setdefault("enabled", True)
    s["alerts"] = {**cfg["alerts"], **s.get("alerts", {})}
    return s


def save_state(s):
    s["sent"] = s["sent"][-3000:]
    STATE_FILE.write_text(json.dumps(s))


def get_candles(cfg):
    if cfg["data_provider"] == "xaus":
        return fetch_xaus_m15()
    if cfg["data_provider"] == "oanda":
        return fetch_oanda_m15(cfg["oanda_instrument"], cfg["oanda_token"],
                               cfg["oanda_env"], cfg["candles_count"])
    return fetch_m15(cfg["symbol"], cfg["twelvedata_api_key"], cfg["candles_count"])


def compute_events(cfg, m15):
    if cfg["mode"] == "m15_breaks":
        return [Event("M15_BREAK", b.time, b.dir, ("M15",), b.level, b.close)
                for b in line_breaks(m15, "M15", cfg["swing_length_lower"])]
    h4 = resample(m15, 240, cfg["h4_anchor_tz"], cfg["h4_anchor_hour"])
    lower = []
    for name in cfg["lower_timeframes"]:
        bars = m15 if name == "M15" else resample(m15, LOWER[name])
        lower += line_breaks(bars, name, cfg["swing_length_lower"])
    return run_cycle(line_breaks(h4, "H4", cfg["swing_length_h4"]), lower)


def fmt(e, last_close, ema_val, cfg):
    side = "BULLISH" if e.dir == 1 else "BEARISH"
    icon = "🟢" if e.dir == 1 else "🔴"
    t = e.time.astimezone(IST).strftime("%d %b %H:%M IST")
    sym = cfg["symbol"]
    if e.kind == "M15_BREAK":
        head = f"{icon} {sym} M15 line break {'UP' if e.dir == 1 else 'DOWN'}"
    elif e.kind == "H4_BO":
        head = f"{icon} {sym} H4 {side} BREAKOUT (close-based)"
    elif e.kind == "OP":
        head = f"🟡 {sym} OP: first opposite break ({', '.join(e.tfs)}) in {side} cycle"
    else:
        head = f"✅ {sym} CF: {side} confirmation ({', '.join(e.tfs)})"
    body = f"Broke {e.level:.2f} | Close {e.price:.2f}\n{t}"
    if ema_val is not None:
        pos = "above" if last_close > ema_val else "below"
        body += f"\nEMA{cfg['ema_length']} (M15): {ema_val:.2f}, price {pos}"
    return head + "\n" + body


def status(state, cfg):
    a = state["alerts"]
    on = lambda k: "ON" if a.get(k) else "OFF"
    s, e = cfg["window_ist"]
    head = "Alerts: ON" if state["enabled"] else "Alerts: PAUSED (send /on to resume)"
    return (f"{head}\nActive window: {s}-{e} IST\n"
            f"M15 {on('m15')} | H4 BO {on('h4_bo')} | OP {on('op')} | CF {on('cf')}\n"
            "Commands: /off  /on  /status  /m15 on|off  /h4bo /op /cf on|off")


def run_check(cfg, state, tg):
    m15 = get_candles(cfg)
    if not m15:
        raise RuntimeError("no candles returned")
    events = compute_events(cfg, m15)
    ema_val = ema([b.c for b in m15], cfg["ema_length"])
    now = datetime.now(UTC)
    sent = set(state["sent"])
    first = not state["initialized"]
    max_age = timedelta(minutes=cfg["max_alert_age_min"])
    for e in events:
        key = f"{e.kind}|{e.time.isoformat()}|{e.dir}"
        if key in sent:
            continue
        sent.add(key)
        state["sent"].append(key)
        if first or not state["enabled"]:
            continue  # old history on first start / alerts paused: stay silent
        if not state["alerts"].get(KIND_KEY[e.kind], True):
            continue
        if not in_window(e.time, *cfg["window_ist"]):
            continue
        if now - e.time > max_age:
            continue
        tg.send(fmt(e, m15[-1].c, ema_val, cfg))
        log.info("sent %s", key)
    state["initialized"] = True
    save_state(state)
    if first:
        tg.send("✅ Gold alerts connected.\n" + status(state, cfg))
    return m15[-1].end


def handle_commands(tg, state, cfg, timeout=15):
    for u in tg.updates(state["tg_offset"], timeout=timeout):
        state["tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != tg.chat_id:
            continue  # ignore anyone else
        parts = (msg.get("text") or "").strip().lower().split()
        if not parts:
            continue
        cmd = parts[0].split("@")[0]
        reply = False
        if cmd == "/off":
            state["enabled"], reply = False, True
        elif cmd == "/on":
            state["enabled"], reply = True, True
        elif cmd in KEYS and len(parts) == 2 and parts[1] in ("on", "off"):
            state["alerts"][KEYS[cmd]], reply = parts[1] == "on", True
        elif cmd in ("/status", "/start", "/help"):
            reply = True
        save_state(state)
        if reply:
            tg.send(status(state, cfg))


def floor15(dt):
    return dt.replace(minute=dt.minute // 15 * 15, second=0, microsecond=0)


def run_once():
    cfg = load_config()
    state = load_state(cfg)
    tg = Telegram(cfg["telegram_bot_token"], cfg["telegram_chat_id"])
    try:
        handle_commands(tg, state, cfg, timeout=0)
    except Exception as ex:
        log.error("telegram commands: %s", ex)
    run_check(cfg, state, tg)  # errors fail the job so GitHub emails you


def main():
    cfg = load_config()
    state = load_state(cfg)
    tg = Telegram(cfg["telegram_bot_token"], cfg["telegram_chat_id"])
    next_poll, retries, fails = 0.0, 0, 0
    while True:
        now = time.time()
        if now >= next_poll:
            try:
                last_end = run_check(cfg, state, tg)
                fails = 0
                nowdt = datetime.now(UTC)
                lag = floor15(nowdt) - last_end
                if timedelta(0) < lag <= timedelta(minutes=30) and retries < 8:
                    retries += 1           # feed is a little late: retry soon
                    next_poll = now + 20
                else:                      # weekend / on time: wait for next candle
                    retries = 0
                    nxt = floor15(nowdt) + timedelta(minutes=15)
                    next_poll = nxt.timestamp() + cfg["poll_delay_sec"]
            except Exception as ex:
                fails += 1
                log.error("check failed: %s", ex)
                if fails == 3:
                    try:
                        tg.send(f"⚠️ Data problem: {ex}")
                    except Exception:
                        pass
                next_poll = now + 60
        try:
            handle_commands(tg, state, cfg, timeout=15)
        except Exception as ex:
            log.error("telegram: %s", ex)
            time.sleep(5)


if __name__ == "__main__":
    run_once() if "--once" in sys.argv else main()
