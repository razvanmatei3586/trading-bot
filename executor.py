# executor.py
import math, time
from datetime import datetime
import pytz
from typing import Optional
from ib_insync import Stock, Order, LimitOrder, MarketOrder
from ibkr import ib  # your connected IB instance

NY = pytz.timezone("America/New_York")

# ---------- hard risk rails (tune in config) ----------
MAX_POSITION_DOLLARS = 50_000
MAX_POSITION_SHARES  = 2_000
MAX_GROSS_EXPOSURE   = 250_000
MAX_DAILY_LOSS       = 5_000
ALLOW_OUTSIDE_RTH    = False
TIF_DEFAULT          = "DAY"

def _now_ny():
    return datetime.now(NY)

def _is_rth(now=None):
    now = now or _now_ny()
    # Simple RTH gate: 9:30–16:00 ET, no holidays (add market calendar later)
    m = now.hour*60 + now.minute
    return 9*60 + 30 <= m <= 16*60

def _account_equity() -> float:
    ib.reqAccountSummary()
    time.sleep(0.2)
    for tag in ib.accountSummary():
        if tag.tag in ("NetLiquidationByCurrency", "NetLiquidation"):
            try:
                return float(tag.value)
            except: pass
    return 0.0

def position_size_by_risk(entry: float, stop: float, risk_pct: float = 0.002) -> int:
    """
    Risk-based sizing. Example: risk 0.2% of equity per trade.
    """
    eq = _account_equity()
    risk_dollars = eq * risk_pct
    stop_dist = abs(entry - stop)
    if stop_dist <= 0 or risk_dollars <= 0:
        return 0
    shares = math.floor(risk_dollars / stop_dist)
    return max(0, shares)

def _cap_by_limits(symbol: str, shares: int, price: float) -> int:
    if shares <= 0: return 0
    # Per-symbol caps
    shares = min(shares, MAX_POSITION_SHARES)
    dollars = shares * price
    if dollars > MAX_POSITION_DOLLARS:
        shares = math.floor(MAX_POSITION_DOLLARS / max(price, 0.01))
    return max(0, shares)

def _ensure_contract(symbol: str):
    c = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(c)
    return c

def place_bracket_buy(
    symbol: str,
    entry_price: float,
    take_profit_price: float,
    stop_loss_price: float,
    qty: int,
    entry_type: str = "LMT",   # "MKT" or "LMT"
    tif: str = TIF_DEFAULT,
    outsideRth: bool = ALLOW_OUTSIDE_RTH,
):
    """
    Classic IBKR bracket: parent BUY, children SELL TP & STP.
    """
    assert qty > 0
    contract = _ensure_contract(symbol)

    if entry_type == "MKT":
        parent = MarketOrder("BUY", qty, tif=tif, outsideRth=outsideRth)
    else:
        parent = LimitOrder("BUY", qty, entry_price, tif=tif, outsideRth=outsideRth)

    parent.transmit = False  # send with children

    tp = LimitOrder("SELL", qty, round(take_profit_price, 2), tif=tif, outsideRth=outsideRth)
    tp.parentId = 0  # will be set by TWS automatically when placed after parent

    sl = Order()
    sl.action = "SELL"
    sl.orderType = "STP"
    sl.auxPrice = round(stop_loss_price, 2)
    sl.totalQuantity = qty
    sl.tif = tif
    sl.outsideRth = outsideRth
    sl.parentId = 0

    # transmit only on the last child
    tp.transmit = False
    sl.transmit = True

    # Place bracket
    ib.placeOrder(contract, parent)
    ib.placeOrder(contract, tp)
    ib.placeOrder(contract, sl)

    return {"symbol": symbol, "qty": qty, "entry": entry_price, "tp": take_profit_price, "sl": stop_loss_price}

def submit_long_from_signal(
    symbol: str,
    last_price: float,
    stop_price: float,
    take_profit_rr: float = 2.0,   # TP at 2R by default
    risk_pct: float = 0.002,       # 0.2% of equity
    entry_slippage: float = 0.001, # 0.1% cushion for limit entry
    entry_type: str = "LMT",
):
    """
    Turn a long signal into a bracket order with risk sizing and guardrails.
    """
    if not ALLOW_OUTSIDE_RTH and not _is_rth():
        print("⛔ Outside RTH; order blocked.")
        return None

    if stop_price >= last_price:
        print("⛔ Invalid stop (must be below entry for longs).")
        return None

    entry = last_price * (1 + (entry_slippage if entry_type == "LMT" else 0.0))
    r = entry - stop_price
    tp = entry + take_profit_rr * r

    qty = position_size_by_risk(entry, stop_price, risk_pct=risk_pct)
    qty = _cap_by_limits(symbol, qty, entry)
    if qty <= 0:
        print("⛔ Size computed as zero; not submitting.")
        return None

    return place_bracket_buy(
        symbol=symbol,
        entry_price=round(entry, 2),
        take_profit_price=round(tp, 2),
        stop_loss_price=round(stop_price, 2),
        qty=qty,
        entry_type=entry_type
    )
