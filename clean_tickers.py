def is_valid_equity_symbol(symbol: str) -> bool:
    """
    Rough filter for valid common stock symbols.
    """
    bad_suffixes = ("W", "WS", "WT", "U", "UN", "R")
    if any(symbol.endswith(s) for s in bad_suffixes):
        return False
    if "^" in symbol or "." in symbol or "-" in symbol:
        return False
    if not symbol.isalpha():
        return False
    return True

def clean_tickers(in_file="all-tickers.txt", out_file="clean-tickers.txt"):
    with open(in_file, "r") as f:
        tickers = [line.strip().upper() for line in f if line.strip()]
    
    valid = [t for t in tickers if is_valid_equity_symbol(t)]
    
    with open(out_file, "w") as f:
        f.write("\n".join(valid))
    
    print(f"✅ Cleaned {len(valid)} tickers written to {out_file}")

if __name__ == "__main__":
    clean_tickers()
