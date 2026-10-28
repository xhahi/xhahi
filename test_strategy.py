import random
from datetime import datetime, timedelta, timezone

from gold_alerts.data import bucket_start, resample
from gold_alerts.strategy import Bar, Break, in_window, line_breaks, run_cycle

UTC = timezone.utc
T0 = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)


def mk(closes, step=15, t0=T0):
    out = []
    for i, c in enumerate(closes):
        s = t0 + timedelta(minutes=step * i)
        out.append(Bar(s, s + timedelta(minutes=step), c, c, c, c))
    return out


def test_wicks_do_not_break():
    # close never exceeds 10, but the wick does
    bars = mk([5, 8, 10, 8, 6, 8, 9])
    bars[-1] = Bar(bars[-1].start, bars[-1].end, 9, 12, 9, 9)
    assert line_breaks(bars, "M15", 2) == []


def test_close_breaks_once():
    bars = mk([5, 8, 10, 8, 6, 8, 11, 12, 13])
    br = line_breaks(bars, "M15", 2)
    assert len(br) == 1 and br[0].dir == 1 and br[0].level == 10 and br[0].close == 11


def b(minute, tf, d):
    return Break(T0 + timedelta(minutes=minute), tf, d, 100.0, 101.0)


def test_cycle_one_op_many_cf():
    h4 = [b(0, "H4", 1), b(600, "H4", -1)]
    low = [b(15, "M15", 1),    # before OP -> ignored
           b(30, "M15", -1),   # OP
           b(45, "M30", -1),   # extra opposite -> no second OP
           b(60, "M15", 1),    # CF
           b(75, "M15", 1),    # CF again
           b(615, "M15", 1)]   # OP of the new bearish cycle
    ev = run_cycle(h4, low)
    kinds = [(e.kind, e.dir) for e in ev]
    assert kinds == [("H4_BO", 1), ("OP", 1), ("CF", 1), ("CF", 1),
                     ("H4_BO", -1), ("OP", -1)]


def test_op_and_cf_same_candle():
    ev = run_cycle([b(0, "H4", 1)], [b(30, "M15", -1), b(30, "H1", 1)])
    assert [e.kind for e in ev] == ["H4_BO", "OP", "CF"]


def test_lower_break_on_h4_candle_ignored():
    ev = run_cycle([b(240, "H4", 1)], [b(240, "M15", -1)])
    assert [e.kind for e in ev] == ["H4_BO"]


def test_alert_window_ist():
    assert in_window(datetime(2026, 10, 26, 0, 30, tzinfo=UTC))      # 06:00 IST
    assert not in_window(datetime(2026, 10, 26, 0, 29, tzinfo=UTC))  # 05:59 IST
    assert in_window(datetime(2026, 10, 26, 14, 30, tzinfo=UTC))     # 20:00 IST
    assert not in_window(datetime(2026, 10, 26, 14, 31, tzinfo=UTC))


def test_h4_alignment_ny17():
    # Oct 26 2026 = EDT, so 17:00 NY = 21:00 UTC; H4 bars open 21,01,05,09,13,17 UTC
    ts = datetime(2026, 10, 26, 10, 7, tzinfo=UTC)
    assert bucket_start(ts, 240, "America/New_York", 17) == datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
    # after DST ends (Nov 2) bars shift to 22,02,06,10,14,18 UTC
    ts = datetime(2026, 11, 2, 10, 7, tzinfo=UTC)
    assert bucket_start(ts, 240, "America/New_York", 17) == datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def test_resample_h4_only_complete():
    m15 = mk([100 + i for i in range(40)], t0=datetime(2026, 10, 26, 9, 0, tzinfo=UTC))
    h4 = resample(m15, 240, "America/New_York", 17)
    # 09:00-13:00 complete (16 bars); 13:00-17:00 complete (16); 17:00+ partial -> dropped
    assert [x.start.hour for x in h4] == [9, 13]
    assert h4[0].o == 100 and h4[0].c == 115 and h4[0].h == 115 and h4[0].l == 100


def test_smoke_random_walk():
    random.seed(7)
    p, closes = 4700.0, []
    for _ in range(3000):
        p += random.gauss(0, 2.5)
        closes.append(p)
    m15 = mk(closes, t0=datetime(2026, 9, 1, 0, 0, tzinfo=UTC))
    h4 = line_breaks(resample(m15, 240, "America/New_York", 17), "H4", 2)
    low = []
    for name, mins in (("M15", 15), ("M30", 30), ("H1", 60)):
        bars = m15 if mins == 15 else resample(m15, mins)
        low += line_breaks(bars, name, 2)
    ev = run_cycle(h4, low)
    kinds = [e.kind for e in ev]
    print("H4 BO:", kinds.count("H4_BO"), "OP:", kinds.count("OP"), "CF:", kinds.count("CF"))
    assert kinds.count("OP") <= kinds.count("H4_BO")
    assert kinds[0] == "H4_BO"
    # OP never appears twice in a row without an H4 BO between them
    last = None
    for k in kinds:
        assert not (k == "OP" and last == "OP")
        if k == "H4_BO":
            last = None
        elif k == "OP":
            last = "OP"
