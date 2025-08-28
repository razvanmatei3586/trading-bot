from ibkr import connect_ib, graceful_disconnect
from strategy import ask_bot
from scanner import scan_with_cache
import signal

UNIVERSE = "clean-tickers.txt"      # your ticker universe file
CACHE = "sma_cache.parquet"         # your SMA cache file

def handle_suspend(signum, frame):
    print("⚠️ Suspend requested (Ctrl+Z). Cleaning up IBKR connection...")
    graceful_disconnect()
    raise SystemExit(0)

# Trap Ctrl+Z (SIGTSTP)
signal.signal(signal.SIGTSTP, handle_suspend)


def main():
    connect_ib()
    df, missing = scan_with_cache(universe_file=UNIVERSE, cache_path=CACHE, batch_size=20, wait_seconds=1.6)
    print("\n=== (Cached) Tickers above SMA50/100/200 ===")
    print(df.to_string(index=False) if not df.empty else "None matched.")
    if missing:
        print(f"\nMissing from cache ({len(missing)}): {missing[:20]} ...")
    graceful_disconnect()


if __name__ == "__main__":
    try:
        main()
    finally:
        graceful_disconnect()
