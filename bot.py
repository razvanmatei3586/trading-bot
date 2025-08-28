# --- CONFIG ---
USE_OPENAI = False  # # Set to True to use OpenAI GPT model, False to use Ollama
MODEL_NAME = "mistral"   # change to "mistral", "llama3", "gemma", "codellama", etc.

# --- Fix for "no current event loop" on macOS / Streamlit ---
import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

# --- Ignore various warnings  ---
import warnings, logging
warnings.filterwarnings("ignore", message="Could get FontBBox")
warnings.filterwarnings("ignore", message="Cannot set gray non-stroke color")
warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")
logging.getLogger("matplotlib").setLevel(logging.ERROR)

import os
import re
import time
import pandas as pd
import matplotlib
from ib_insync import *       # IBKR API
from langchain_community.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain.chains import RetrievalQA
from dotenv import load_dotenv     # For IBKR connection settings

# --- Embeddings + LLM setup ---
if USE_OPENAI:
    # --- GPT-4o-mini Model ---
    from langchain_openai import OpenAIEmbeddings, ChatOpenAI
    embeddings = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))
    llm = ChatOpenAI(openai_api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o-mini")
else:
    # --- Local AI Model (via Ollama) ---
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_ollama import OllamaLLM
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    llm = OllamaLLM(model=MODEL_NAME)

# --- Load environment variables ---
load_dotenv()

# --- Fix the font parsing issues (non-GUI backend) ---
matplotlib.use("Agg") 


# --- Load Strategy Documents ---
loader = DirectoryLoader("strategy_docs", glob="**/*.*")
docs = loader.load()

splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
chunks = splitter.split_documents(docs)

db = Chroma.from_documents(chunks, embeddings, persist_directory="strategy_db")

retriever = db.as_retriever()
qa = RetrievalQA.from_chain_type(llm=llm, retriever=retriever)


# --- IBKR Connection with Calm Auto-Reconnect ---
import threading, time
ib = IB()

HOST = os.getenv("IB_HOST")
PORT = int(os.getenv("IB_PORT"))
BASE_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))

# Shared state for reconnection
_reconnect_lock = threading.Lock()
_reconnect_in_progress = False
_current_client_id = None  # remember which id worked


def _try_connect(client_id):
    """Try a single connect with this client_id, return True/False."""
    try:
        if ib.isConnected():
            ib.disconnect()
        ib.connect(HOST, PORT, clientId=client_id)
        return True
    except Exception as e:
        print(f"connect(clientId={client_id}) failed: {e}")
        return False


def _connect_initial_with_fallback(base_id=BASE_CLIENT_ID, max_tries=10):
    """Initial connect: step clientId only if 'in use'; for timeouts just retry."""
    global _current_client_id
    client_id = base_id
    for attempt in range(max_tries):
        if _try_connect(client_id):
            _current_client_id = client_id
            print(f"✅ Connected to IBKR (clientId={client_id})")
            return
        if attempt % 2 == 1:  # every 2nd attempt, bump id in case it's stuck
            client_id += 1
        time.sleep(2 + attempt)
    print("❌ Initial connect failed after retries.")


def _schedule_reconnect():
    """Start one background reconnect worker with exponential backoff."""
    global _reconnect_in_progress, _current_client_id

    with _reconnect_lock:
        if _reconnect_in_progress:
            return
        _reconnect_in_progress = True

    def worker():
        global _reconnect_in_progress, _current_client_id
        delays = [2, 5, 10, 20, 30, 60, 90, 120]
        for d in delays:
            cid = _current_client_id or BASE_CLIENT_ID
            if _try_connect(cid):
                _current_client_id = cid
                print(f"🔄 Reconnected to IBKR (clientId={cid})")
                break
            alt_cid = cid + 1
            if _try_connect(alt_cid):
                _current_client_id = alt_cid
                print(f"🔄 Reconnected to IBKR (clientId={alt_cid})")
                break
            print(f"…retrying in {d}s")
            time.sleep(d)
        with _reconnect_lock:
            _reconnect_in_progress = False

    threading.Thread(target=worker, daemon=True).start()


def _on_disconnect():
    print("⚠️ Disconnected from IBKR. Scheduling reconnect…")
    try:
        _schedule_reconnect()
    except Exception as e:
        print(f"Reconnect scheduling error: {e}")


# Subscribe to the disconnect event
ib.disconnectedEvent += _on_disconnect

# Initial connect
_connect_initial_with_fallback()


# --- Core Bot Functions ---
def get_sma_and_last_price(ticker, lengths=(50,100,200)):
    """
    Fetch 1 year of daily bars for a ticker, return last price and SMAs.
    Uses only historical data (faster + avoids duplicate API calls).
    """
    contract = Stock(ticker, "SMART", "USD")
    try:
        ib.qualifyContracts(contract)
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1 Y",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1
        )
        if not bars:
            return None, {}

        df = util.df(bars).sort_values("date")
        last_price = df["close"].iloc[-1]

        smas = {}
        for l in lengths:
            if len(df) >= l:
                smas[l] = round(df["close"].rolling(window=l).mean().iloc[-1], 2)

        return last_price, smas
    except Exception:
        return None, {}

def get_realtime_price_snapshot(ticker):
    contract = Stock(ticker, "SMART", "USD")
    ib.qualifyContracts(contract)
    # snapshot=True -> one-shot
    tkr = ib.reqMktData(contract, snapshot=True)
    ib.sleep(1.5)  # brief wait for snapshot to fill
    price = tkr.marketPrice()
    # Safety: cancel in case API returned streaming by permission
    ib.cancelMktData(contract)
    return price


def ask_bot(query):
    # Normalize query
    normalized_query = re.sub(r"\$([A-Z]{1,5})", r"\1", query)

    # Answer from strategy docs
    answer = qa.run(normalized_query)

    # Detect tickers with $ prefix
    ticker_pattern = re.compile(r"\$[A-Z]{1,5}")
    tickers = ticker_pattern.findall(query)

    for t in tickers:
        ticker = t[1:]  # strip "$"
        try:
            # Real intraday price (snapshot, safe)
            price = get_realtime_price_snapshot(ticker)

            # Historical SMAs
            _, smas = get_sma_and_last_price(ticker)

            if price and price == price:  # check not NaN
                answer += f"\n\n💡 {ticker} current price: ${round(price,2)}."

            if smas:
                sma_text = ", ".join([f"SMA{l}={smas[l]}" for l in smas])
                answer += f" Key SMAs: {sma_text}."

                # Interpretation
                signals = []
                for l, v in smas.items():
                    if price > v:
                        signals.append(f"above SMA{l}")
                    elif price < v:
                        signals.append(f"below SMA{l}")
                    else:
                        signals.append(f"at SMA{l}")

                if signals:
                    trend = "; ".join(signals)
                    answer += f" 📊 Trend check: price is {trend}."

        except Exception as e:
            print(f"Could not fetch indicators for {ticker}: {e}")

    return answer


def scan_all_tickers(universe_file="clean-tickers.txt", lengths=(50,100,200),
                     lookback="1 Y", sleep_between=0.8):
    """
    Scan tickers and return those where last price > all SMAs.
    Faster (only 1 API call/ticker), resilient (skips bad ones).
    """
    results, errors = [], []

    with open(universe_file, "r") as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    for i, t in enumerate(tickers, 1):
        last_price, smas = get_sma_and_last_price(t, lengths=lengths)

        if last_price and smas and all(last_price > smas[l] for l in lengths if l in smas):
            results.append({
                "ticker": t,
                "price": round(last_price, 2),
                "SMA50": smas.get(50),
                "SMA100": smas.get(100),
                "SMA200": smas.get(200),
            })
        elif not smas:  
            errors.append(t)

        # pacing to respect IBKR limits
        time.sleep(sleep_between)

        if i % 25 == 0:
            print(f"✅ Scanned {i}/{len(tickers)} tickers...")

    df = pd.DataFrame(results).sort_values("price", ascending=False)
    return df, errors


    # Load tickers from file
    with open(universe_file, "r") as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    for t in tickers:
        try:
            price = get_price(t)
            smas = get_sma(t, lengths=lengths)

            if not smas or price != price:  # NaN check
                continue

            if all(price > smas[l] for l in lengths if l in smas):
                results.append({
                    "ticker": t,
                    "price": round(price, 2),
                    **{f"SMA{l}": smas[l] for l in smas}
                })

        except Exception as e:
            errors.append((t, str(e)))

        # Sleep a bit to respect IBKR pacing
        time.sleep(sleep_between)

    return pd.DataFrame(results), errors



# TEST SECTION
#if __name__ == "__main__":
#    query = "What should I do with $AAPL today?"
#    print(ask_bot(query))

if __name__ == "__main__":
    df, errs = scan_all_tickers()
    print("\n=== Tickers above SMA50, SMA100, SMA200 ===")
    print(df.head(20).to_string(index=False))  # print first 20 results
    print(f"\nErrors: {len(errs)}")