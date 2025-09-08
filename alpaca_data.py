# alpaca_data.py
"""
Alpaca Market Data v2 client (REST + WebSocket) for your trading-bot.

- REST:
    • /v2/stocks/bars (multi-symbol)
    • /v2/stocks/snapshots (multi-symbol)
- WS:
    • wss://stream.data.alpaca.markets/v2/{feed}  (feed = "iex" or "sip")
    • subscribe to trades / quotes / bars for many symbols

ENV VARIABLES
-------------
APCA-API-KEY-ID        = your key id (required)
APCA-API-SECRET-KEY    = your secret (required)
ALPACA_MAX_RPS           = max REST requests per second (default: 10)
ALPACA_REST_BASE         = override REST base (default: https://data.alpaca.markets/v2)
ALPACA_WS_BASE           = override WS base  (default: wss://stream.data.alpaca.markets/v2)

USAGE EXAMPLES
--------------
# 1) REST: last 100 1-min bars for 3 symbols
python alpaca_data.py bars --symbols "AAPL,MSFT,SPY" --timeframe 1Min --limit 100

# 2) REST: multi-symbol snapshots
python alpaca_data.py snapshots --symbols "AAPL,MSFT,SPY"

# 3) WS: stream quotes for 3 symbols (CTRL+C to stop)
python alpaca_data.py ws --quotes "AAPL,MSFT,SPY"

# 4) WS: stream trades + bars for 100+ symbols
python alpaca_data.py ws --trades "AAPL,...,ZZZZ" --bars "AAPL,...,ZZZZ"
"""

from __future__ import annotations

import argparse
import json
import os
import time
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests
from dateutil import parser as dateparse
from websocket import WebSocketApp


# ---------- Config ----------

from dataclasses import dataclass
import os

@dataclass
class AlpacaConfig:
    # Prefer the official underscore envs; fall back to ALPACA_* if you used those earlier
    key_id: str = (
        os.getenv("APCA-API-KEY-ID")
        or os.getenv("ALPACA_API_KEY_ID", "")
    )
    secret: str = (
        os.getenv("APCA-API-SECRET-KEY")
        or os.getenv("ALPACA_API_SECRET_KEY", "")
    )

    rest_base: str = os.getenv("APCA_REST_BASE", "https://data.alpaca.markets/v2")
    ws_base: str   = os.getenv("APCA_WS_BASE",   "wss://stream.data.alpaca.markets/v2")
    max_rps: float = float(os.getenv("APCA_MAX_RPS", os.getenv("ALPACA_MAX_RPS", "10")))

    def validate(self):
        if not self.key_id or not self.secret:
            raise RuntimeError(
                "Set APCA-API-KEY-ID and APCA-API-SECRET-KEY in your environment (or pass via CLI)."
            )
        if self.feed not in ("iex", "sip"):
            raise RuntimeError("Feed must be 'iex' or 'sip'.")


# ---------- Utilities ----------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _chunks(seq: Iterable[str], n: int) -> Iterable[List[str]]:
    buf: List[str] = []
    for s in seq:
        if not s:
            continue
        buf.append(s)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf

def _throttle(last_ts: List[float], max_rps: float):
    """Naive throttle: ensure at most max_rps calls/sec."""
    if max_rps <= 0:
        return
    min_interval = 1.0 / max_rps
    now = time.perf_counter()
    delta = now - last_ts[0]
    if delta < min_interval:
        time.sleep(min_interval - delta)
    last_ts[0] = time.perf_counter()

def _iso(dt_str: Optional[str]) -> Optional[str]:
    if not dt_str:
        return None
    # accept "2025-09-04", "2025-09-04T13:00:00Z", etc.
    return dateparse.parse(dt_str).astimezone(timezone.utc).isoformat()

# ---------- REST Client ----------

class AlpacaDataClient:
    def __init__(self, cfg: Optional[AlpacaConfig] = None):
        self.cfg = cfg or AlpacaConfig()
        self.cfg.validate()
        self.sess = requests.Session()
        self.sess.headers.update({
            "APCA-API-KEY-ID": self.cfg.key_id,
            "APCA-API-SECRET-KEY": self.cfg.secret,
        })
        self._last_call = [0.0]

    def _get(self, path: str, params: Dict) -> Dict:
        url = f"{self.cfg.rest_base}{path}"
        # throttle to avoid ban / 429
        _throttle(self._last_call, self.cfg.max_rps)

        backoff = 1.0
        for attempt in range(6):
            r = self.sess.get(url, params={k: v for k, v in params.items() if v is not None}, timeout=30)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(backoff)
                backoff = min(backoff * 2, 16.0)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Alpaca GET failed after retries: {url}")

    # ---- Bars (multi-symbol) ----
    def get_bars(
        self,
        symbols: List[str],
        timeframe: str = "1Min",
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: Optional[int] = 1000,
        adjustment: str = "raw",  # "raw" | "split" | "all"
        max_symbols_per_request: int = 50,
    ) -> pd.DataFrame:
        """
        Returns tidy DataFrame: columns = [symbol, t, open, high, low, close, volume, vwap?]
        Time is ISO8601 UTC in column 't'.
        """
        symbols = sorted({s.strip().upper() for s in symbols if s.strip()})
        frames: List[pd.DataFrame] = []

        for batch in _chunks(symbols, max_symbols_per_request):
            params = {
                "symbols": ",".join(batch),
                "timeframe": timeframe,
                "start": _iso(start),
                "end": _iso(end),
                "limit": limit,
                "adjustment": adjustment,
                "feed": self.cfg.feed,  # "iex" or "sip"
            }
            data = self._get("/stocks/bars", params)
            # shape: { "bars": { "AAPL": [ { "t": "...", "o":..., "h":..., "l":..., "c":..., "v":... }, ... ], ... } }
            bars = data.get("bars", {})
            for sym, rows in bars.items():
                if not rows:
                    continue
                df = pd.DataFrame(rows)
                df.insert(0, "symbol", sym)
                frames.append(df)

        if not frames:
            return pd.DataFrame(columns=["symbol", "t", "o", "h", "l", "c", "v", "vw"])
        out = pd.concat(frames, ignore_index=True)
        # Normalize types
        out["t"] = pd.to_datetime(out["t"], utc=True)
        return out.sort_values(["symbol", "t"]).reset_index(drop=True)

    # ---- Snapshots (multi-symbol) ----
    def get_snapshots(
        self,
        symbols: List[str],
        max_symbols_per_request: int = 50,
    ) -> pd.DataFrame:
        """
        Multi-symbol snapshots: last trade, best bid/ask, today's OHLC, etc.
        Returns tidy DataFrame with one row per symbol (where available).
        """
        symbols = sorted({s.strip().upper() for s in symbols if s.strip()})
        rows: List[Dict] = []

        for batch in _chunks(symbols, max_symbols_per_request):
            params = {
                "symbols": ",".join(batch),
                "feed": self.cfg.feed,
            }
            data = self._get("/stocks/snapshots", params)
            # shape: { "snapshots": { "AAPL": { "latestTrade": {...}, "latestQuote": {...}, "minuteBar": {...}, "dailyBar": {...}, ... }, ... } }
            snaps = data.get("snapshots", {})
            for sym, snap in snaps.items():
                lt = snap.get("latestTrade") or {}
                lq = snap.get("latestQuote") or {}
                db = snap.get("dailyBar") or {}
                mb = snap.get("minuteBar") or {}
                rows.append({
                    "symbol": sym,
                    "trade_ts": lt.get("t"),
                    "trade_px": lt.get("p"),
                    "quote_ts": lq.get("t"),
                    "bid_px": lq.get("bp"),
                    "bid_sz": lq.get("bs"),
                    "ask_px": lq.get("ap"),
                    "ask_sz": lq.get("as"),
                    "daily_o": db.get("o"),
                    "daily_h": db.get("h"),
                    "daily_l": db.get("l"),
                    "daily_c": db.get("c"),
                    "min_bar_t": mb.get("t"),
                    "min_bar_c": mb.get("c"),
                })

        if not rows:
            return pd.DataFrame(columns=[
                "symbol","trade_ts","trade_px","quote_ts","bid_px","bid_sz","ask_px","ask_sz",
                "daily_o","daily_h","daily_l","daily_c","min_bar_t","min_bar_c"
            ])
        out = pd.DataFrame(rows)
        # Parse timestamps if present
        for col in ("trade_ts", "quote_ts", "min_bar_t"):
            if col in out.columns:
                out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
        return out.sort_values("symbol").reset_index(drop=True)


# ---------- WebSocket (real-time) ----------

class AlpacaWS:
    """
    Simple WS client for trades/quotes/bars.

    Subscribe with lists of symbols. Message types you will see:
      - "t" (trade), "q" (quote), "b" (bar), "error", "success"
    """

    def __init__(
        self,
        cfg: Optional[AlpacaConfig] = None,
        on_trade=None,
        on_quote=None,
        on_bar=None,
        on_error=None,
        on_status=None,
    ):
        self.cfg = cfg or AlpacaConfig()
        self.cfg.validate()
        self.url = f"{self.cfg.ws_base}/{self.cfg.feed}"
        self.on_trade = on_trade
        self.on_quote = on_quote
        self.on_bar = on_bar
        self.on_error = on_error
        self.on_status = on_status
        self.ws: Optional[WebSocketApp] = None

    def _on_open(self, ws):
        # auth first
        auth = {"action": "auth", "key": self.cfg.key_id, "secret": self.cfg.secret}
        ws.send(json.dumps(auth))
        if self.on_status:
            self.on_status("ws_open")

    def _on_message(self, ws, message: str):
        try:
            payload = json.loads(message)
        except Exception:
            if self.on_error:
                self.on_error({"type": "parse_error", "raw": message})
            return
        # Alpaca sends either dict or list; normalize to list
        msgs = payload if isinstance(payload, list) else [payload]
        for m in msgs:
            t = m.get("T") or m.get("t")  # some examples use uppercase T
            if t in ("success", "subscription"):
                if self.on_status:
                    self.on_status(t)
            elif t == "error":
                if self.on_error:
                    self.on_error(m)
            elif t in ("t", "trade"):
                if self.on_trade:
                    self.on_trade(m)
            elif t in ("q", "quote"):
                if self.on_quote:
                    self.on_quote(m)
            elif t in ("b", "bar"):
                if self.on_bar:
                    self.on_bar(m)
            else:
                # unknown / keep-alive
                if self.on_status:
                    self.on_status(f"other:{t}")

    def _on_close(self, ws, code, reason):
        if self.on_status:
            self.on_status(f"ws_close code={code} reason={reason}")

    def _on_error(self, ws, error):
        if self.on_error:
            self.on_error({"type": "ws_error", "error": str(error)})

    def run(
        self,
        trades: List[str] | None = None,
        quotes: List[str] | None = None,
        bars: List[str] | None = None,
        reconnect: bool = True,
    ):
        trades = sorted({s.strip().upper() for s in (trades or []) if s.strip()})
        quotes = sorted({s.strip().upper() for s in (quotes or []) if s.strip()})
        bars   = sorted({s.strip().upper() for s in (bars   or []) if s.strip()})

        self.ws = WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_close=self._on_close,
            on_error=self._on_error,
        )

        def _subscribe():
            subs = {"action": "subscribe"}
            if trades: subs["trades"] = trades
            if quotes: subs["quotes"] = quotes
            if bars:   subs["bars"]   = bars
            self.ws.send(json.dumps(subs))

        # Wrap open to also send subscribe right after auth success
        def _on_message_with_sub(ws, message):
            try:
                payload = json.loads(message)
                msgs = payload if isinstance(payload, list) else [payload]
            except Exception:
                self._on_message(ws, message)  # will route parse_error
                return

            # Pass through
            self._on_message(ws, message)

            # When we see {"T":"success","msg":"authenticated"}, subscribe
            for m in msgs:
                if m.get("T") == "success" and "authenticated" in m.get("msg", "").lower():
                    _subscribe()

        self.ws.on_message = _on_message_with_sub

        backoff = 1.0
        while True:
            try:
                if self.on_status:
                    self.on_status(f"connecting {self.url}")
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except KeyboardInterrupt:
                break
            except Exception as e:
                if self.on_error:
                    self.on_error({"type": "run_exception", "error": str(e)})
            if not reconnect:
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


# ---------- CLI ----------

def _comma_list(s: str) -> List[str]:
    return [x.strip().upper() for x in s.split(",") if x.strip()]

def cli():
    p = argparse.ArgumentParser(description="Alpaca Market Data v2 client (REST + WS)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # Global option (works before/after the subcommand)
    p.add_argument("--feed", choices=["iex", "sip"], help="Data feed to use")

    # REST: bars
    p_bars = sub.add_parser("bars", help="Fetch multi-symbol bars")
    p_bars.add_argument("--symbols", required=True, help="Comma-separated symbols")
    p_bars.add_argument("--timeframe", default="1Min", help="1Min, 5Min, 1Hour, 1Day, ...")
    p_bars.add_argument("--start", default=None, help="ISO8601 or YYYY-MM-DD (UTC)")
    p_bars.add_argument("--end", default=None, help="ISO8601 or YYYY-MM-DD (UTC)")
    p_bars.add_argument("--limit", type=int, default=1000)
    p_bars.add_argument("--adjustment", default="raw")

    # REST: snapshots
    p_snap = sub.add_parser("snapshots", help="Fetch multi-symbol snapshots")
    p_snap.add_argument("--symbols", required=True, help="Comma-separated symbols")

    # WS
    p_ws = sub.add_parser("ws", help="Stream trades/quotes/bars")
    p_ws.add_argument("--trades", default="", help="Comma-separated symbols for trades")
    p_ws.add_argument("--quotes", default="", help="Comma-separated symbols for quotes")
    p_ws.add_argument("--bars",   default="", help="Comma-separated symbols for bars")

    args = p.parse_args()
    cfg = AlpacaConfig()
    if getattr(args, "feed", None):    
        cfg.feed = args.feed
    cfg.validate()

    if args.cmd == "bars":
        client = AlpacaDataClient(cfg)
        df = client.get_bars(
            symbols=_comma_list(args.symbols),
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            limit=args.limit,
            adjustment=args.adjustment,
        )
        # Print tidy CSV to stdout
        if df.empty:
            print("symbol,t,o,h,l,c,v,vw")
        else:
            print(df.to_csv(index=False))

    elif args.cmd == "snapshots":
        client = AlpacaDataClient(cfg)
        df = client.get_snapshots(_comma_list(args.symbols))
        if df.empty:
            print("symbol,trade_ts,trade_px,quote_ts,bid_px,bid_sz,ask_px,ask_sz,daily_o,daily_h,daily_l,daily_c,min_bar_t,min_bar_c")
        else:
            # Cast floats nicely
            with pd.option_context("display.float_format", lambda v: f"{v:.6f}"):
                print(df.to_csv(index=False))

    elif args.cmd == "ws":
        trades = _comma_list(args.trades)
        quotes = _comma_list(args.quotes)
        bars   = _comma_list(args.bars)

        def on_status(msg): print(f"[{_now_utc().isoformat()}] status: {msg}")
        def on_error(err):  print(f"[{_now_utc().isoformat()}] error: {err}")
        def on_trade(m):    print(json.dumps({"type":"trade","S":m.get("S"),"p":m.get("p"),"s":m.get("s"),"t":m.get("t")}))
        def on_quote(m):    print(json.dumps({"type":"quote","S":m.get("S"),"bp":m.get("bp"),"ap":m.get("ap"),"bs":m.get("bs"),"as":m.get("as"),"t":m.get("t")}))
        def on_bar(m):      print(json.dumps({"type":"bar","S":m.get("S"),"o":m.get("o"),"h":m.get("h"),"l":m.get("l"),"c":m.get("c"),"v":m.get("v"),"t":m.get("t")}))

        ws = AlpacaWS(cfg, on_trade, on_quote, on_bar, on_error, on_status)
        try:
            ws.run(trades=trades, quotes=quotes, bars=bars, reconnect=True)
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    cli()
