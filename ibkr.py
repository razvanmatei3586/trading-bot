import time, threading
from ib_insync import IB, Stock
from utils import load_config

cfg = load_config()
ib = IB()

HOST = cfg["IB_HOST"]
PORT = cfg["IB_PORT"]
BASE_CLIENT_ID = cfg["IB_CLIENT_ID"]

_reconnect_lock = threading.Lock()
_reconnect_in_progress = False
_current_client_id = None
_shutting_down = False
_reqid_to_symbol = {}

def _try_connect(client_id: int) -> bool:
    try:
        if ib.isConnected():
            ib.disconnect()
        ib.connect(HOST, PORT, clientId=client_id)
        # Use delayed data if you prefer / lack real-time permissions:
        # ib.reqMarketDataType(3)  # 1=real-time,2=freeze,3=delayed,4=delayed-frozen
        return True
    except Exception as e:
        print(f"connect(clientId={client_id}) failed: {e}")
        return False

def connect_ib():
    """Initial connect with fallback on clientId collisions."""
    global _current_client_id

    cid = BASE_CLIENT_ID
    for attempt in range(10):
        if _try_connect(cid):
            _current_client_id = cid
            print(f"✅ Connected to IBKR (clientId={cid})")

            # --- Attach error handler once ---
            def custom_error_handler(reqId, errorCode, errorString, contract):
                # Ignore noisy farm connect messages
                if errorCode in (2104, 2106, 2119):
                    return
                sym = _reqid_to_symbol.get(reqId)
                if not sym and contract and hasattr(contract, "symbol"):
                    sym = contract.symbol

                if errorCode == 300:  # No security definition
                    print(f"⚠️ Skipping {sym or reqId}: {errorString}")
                else:
                    print(f"❌ IBKR Error {errorCode} (reqId {reqId}, sym={sym}): {errorString}")

            ib.errorEvent += custom_error_handler
            return

        if attempt % 2 == 1:
            cid += 1
        time.sleep(2 + attempt)

    raise RuntimeError("❌ Could not connect to IBKR after retries")


def _schedule_reconnect():
    """Background reconnect with exponential backoff; never raises."""
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
            alt = cid + 1
            if _try_connect(alt):
                _current_client_id = alt
                print(f"🔄 Reconnected to IBKR (clientId={alt})")
                break
            print(f"...retrying in {d}s")
            time.sleep(d)
        with _reconnect_lock:
            _reconnect_in_progress = False

    threading.Thread(target=worker, daemon=True).start()

def _on_disconnect():
    if _shutting_down:
        # We intended to disconnect; stay quiet.
        print("ℹ️ IBKR disconnected (graceful shutdown).")
        return
    print("⚠️ IBKR disconnected. Scheduling reconnect…")
    try:
        _schedule_reconnect()
    except Exception as e:
        print(f"Reconnect scheduling error: {e}")
ib.disconnectedEvent += _on_disconnect

# --- Helpers ---

def get_realtime_price_snapshot(ticker: str):
    try:
        contract = Stock(ticker, "SMART", "USD")
        ib.qualifyContracts(contract)

        rid = ib.client.getReqId()
        _reqid_to_symbol[rid] = ticker

        ib.client.reqMktData(rid, contract, "", True, False, [])
        ib.sleep(1.5)

        tkr = ib.ticker(contract)
        price = tkr.marketPrice() if tkr else None

        # ❌ remove cancel for snapshots (they auto-end)
        # ib.client.cancelMktData(rid)

        return price
    except Exception as e:
        print(f"snapshot {ticker} failed: {e}")
        return None


def graceful_disconnect():
    """Tell the reconnect handler not to auto-reconnect, then disconnect."""
    global _shutting_down
    _shutting_down = True
    try:
        if ib.isConnected():
            ib.disconnect()
            print("👋 Disconnected from IBKR.")
    except Exception as e:
        print(f"Graceful disconnect error: {e}")
