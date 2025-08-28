import os
import warnings
import matplotlib

from dotenv import load_dotenv

# Headless Matplotlib & warning filters (font / urllib3 noise)
matplotlib.use("Agg")
warnings.filterwarnings("ignore", message="Could get FontBBox")
warnings.filterwarnings("ignore", message="Cannot set gray non-stroke color")
warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")

def load_config():
    load_dotenv()
    cfg = {
        "IB_HOST": os.getenv("IB_HOST", "127.0.0.1"),
        "IB_PORT": int(os.getenv("IB_PORT", "7497")),
        "IB_CLIENT_ID": int(os.getenv("IB_CLIENT_ID", "1")),
        "USE_OPENAI": os.getenv("USE_OPENAI", "False").lower() == "true",
        "OLLAMA_MODEL": os.getenv("OLLAMA_MODEL", "mistral"),
    }
    return cfg

# Streamlit / threads can lack an event loop; make sure one exists.
def ensure_asyncio_loop():
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
