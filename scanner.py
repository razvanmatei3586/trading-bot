# scanner.py
import os
import time
import pytz
import pandas as pd
from typing import Dict, List, Tuple
from ib_insync import Stock, util
from ibkr import ib, get_realtime_price_snapshot, _reqid_to_symbol
from datetime import datetime, timedelta

NY_TZ = pytz.timezone("America/New_York")

def ny_now():
    return datetime.now(NY_TZ)

def prev_business_day(d: datetime.date) -> datetime.date:
    wd = d.weekday()  # Mon=0 ... Sun=6
    if wd == 0:       # Monday -> go to Friday
        return d - timedelta(days=3)
    elif wd == 6:     # Sunday -> Friday
        return d - timedelta(days=2)
    else:
        return d - timedelta(days=1)

def expected_cache_date_ny() -> str:
    """
    If it's after 16:15 NY time, expect today's date in cache (market closed).
    Otherwise expect previous business day.
    """
    now = ny_now()
    cutoff = now.replace(hour=16, minute=15, second=0, microsecond=0)
    today = now.date()
    expected = today if now >= cutoff else prev_business_day(today)
    return expected.isoformat()

# ============== HISTORICAL SMA (1 call per ticker) ==============

def get_sma_and_last_price(ticker: str, lengths: Tuple[int, ...] = (50, 100, 200)) -> Tuple[float, Dict[int, float], str]:
    """
    Pull ~1 year of daily bars from IBKR and compute SMAs.
    Returns: (last_close_price, {length: sma_value}, last_bar_date_str)
    """
    try:
        contract = Stock(ticker, "SMART", "USD")
        ib.qualifyContracts(contract)
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1 Y",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        if not bars:
            return None, {}, ""
        df = util.df(bars).sort_values("date")
        last_price = float(df["close"].iloc[-1])
        last_bar_date = pd.to_datetime(df["date"].iloc[-1]).date().isoformat()

        smas = {}
        for l in lengths:
            if len(df) >= l:
                smas[l] = round(float(df["close"].rolling(window=l).mean().iloc[-1]), 2)

        return last_price, smas, last_bar_date
    except Exception:
        return None, {}, ""

# ============== DAILY CACHE (build once after market close) ==============

def build_sma_cache(
    universe_file: str = "clean-tickers.txt",
    cache_path: str = "sma_cache.parquet",
    lengths: Tuple[int, ...] = (50, 100, 200),
    sleep_between: float = 0.8,
) -> None:
    """
    After market close: compute SMA50/100/200 for all tickers and save to Parquet.
    Stamps each ticker with its actual last bar date.
    """
    records = []
    with open(universe_file, "r") as f:
        tickers = [t.strip().upper() for t in f if t.strip()]

    total = len(tickers)
    for i, t in enumerate(tickers, 1):
        _, smas, last_bar_date = get_sma_and_last_price(t, lengths=lengths)
        if smas:
            records.append(
                {
                    "ticker": t,
                    "SMA50": smas.get(50),
                    "SMA100": smas.get(100),
                    "SMA200": smas.get(200),
                    "cache_date": last_bar_date,
                }
            )
        time.sleep(sleep_between)
        if i % 25 == 0:
            print(f"📦 cached {i}/{total}")

    if not records:
        raise RuntimeError("No SMAs computed; cache would be empty.")

    df = pd.DataFrame(records).drop_duplicates(subset=["ticker"]).set_index("ticker")
    df.to_parquet(cache_path)
    print(f"✅ SMA cache written: {cache_path} ({len(df)} tickers)")

def load_sma_cache(cache_path: str = "sma_cache.parquet") -> tuple[pd.DataFrame, str]:
    if not os.path.exists(cache_path):
        raise FileNotFoundError(f"No cache at {cache_path}")
    df = pd.read_parquet(cache_path)
    if "cache_date" not in df.columns:
        df["cache_date"] = ""
    # Use the most common last_bar_date as representative
    cache_date = df["cache_date"].mode().iat[0] if not df["cache_date"].empty else ""
    return df, cache_date

# ============== FAST INTRADAY SCAN USING CACHE ==============

def _snapshot_batch(tickers: List[str], batch_size: int = 20, wait_seconds: float = 1.6) -> Dict[str, float]:
    prices: Dict[str, float] = {}
    for start in range(0, len(tickers), batch_size):
        batch = tickers[start:start+batch_size]
        contracts, tickers_objs = [], []
        for sym in batch:
            try:
                c = Stock(sym, "SMART", "USD")
                ib.qualifyContracts(c)
                tkr = ib.reqMktData(c, snapshot=True)

                if hasattr(tkr, "tickerId") and tkr.tickerId is not None:
                    _reqid_to_symbol[tkr.tickerId] = sym

                contracts.append(c)
                tickers_objs.append((sym, tkr))
            except Exception as e:
                print(f"⚠️ Could not request snapshot for {sym}: {e}")
                continue

        ib.sleep(wait_seconds)

        for sym, tkr in tickers_objs:
            try:
                p = tkr.marketPrice()
                if p and p == p:  # not NaN
                    prices[sym] = float(p)
                else:
                    print(f"⚠️ No price for {sym} (empty snapshot)")
            except Exception as e:
                print(f"⚠️ Could not read price for {sym}: {e}")

        time.sleep(0.1)

    return prices

def scan_with_cache(
    universe_file: str = "clean-tickers.txt",
    cache_path: str = "sma_cache.parquet",
    batch_size: int = 50,
    wait_seconds: float = 0.5,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Intraday fast scan:
      - Load cached SMAs (built once/day)
      - Request *snapshots* in parallel-ish batches (no streaming lines kept open)
      - Return tickers where current price > SMA50/100/200
    """
    cache, cache_date = load_sma_cache(cache_path)

    exp = expected_cache_date_ny()
    if cache_date and cache_date != exp:
        print(f"⚠️ Cache is from {cache_date}, expected {exp}. "
              "Rebuild after market close with build_cache.py if you want fresh SMAs.")
        
    with open(universe_file, "r") as f:
        tickers = [t.strip().upper() for t in f if t.strip()]

    have_cache = [t for t in tickers if t in cache.index]
    missing = [t for t in tickers if t not in cache.index]

    prices = _snapshot_batch(have_cache, batch_size=batch_size, wait_seconds=wait_seconds)

    rows = []
    for sym, price in prices.items():
        row = cache.loc[sym]
        smas = {50: row.get("SMA50"), 100: row.get("SMA100"), 200: row.get("SMA200")}
        if all((smas[k] is not None and price > smas[k]) for k in (50, 100, 200)):
            rows.append(
                {
                    "ticker": sym,
                    "price": round(price, 2),
                    "SMA50": float(smas[50]),
                    "SMA100": float(smas[100]),
                    "SMA200": float(smas[200]),
                }
            )

    df = pd.DataFrame(rows).sort_values("price", ascending=False)
    return df, missing
