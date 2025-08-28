# build_cache.py
from ibkr import connect_ib, graceful_disconnect
from scanner import build_sma_cache

UNIVERSE = "clean-tickers.txt"
CACHE = "sma_cache.parquet"

def main():
    connect_ib()
    build_sma_cache(universe_file=UNIVERSE, cache_path=CACHE, sleep_between=0.8)
    graceful_disconnect()

if __name__ == "__main__":
    main()
