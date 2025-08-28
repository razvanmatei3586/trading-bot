import os, re
from langchain.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaLLM
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.chains import RetrievalQA
from langchain_community.document_loaders import DirectoryLoader, TextLoader

from utils import load_config
from ibkr import get_realtime_price_snapshot
from scanner import get_sma_and_last_price

cfg = load_config()

# --- Embeddings + LLM (local, free)
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
llm = OllamaLLM(model=cfg["OLLAMA_MODEL"])  # e.g. mistral

# --- Load strategy docs (TXT/MD recommended; PDFs can be noisy)
loader = DirectoryLoader("strategy_docs", glob="**/*.txt", loader_cls=TextLoader)
docs = loader.load()

splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
chunks = splitter.split_documents(docs)

db = Chroma.from_documents(chunks, embeddings, persist_directory="strategy_db")
retriever = db.as_retriever()
qa = RetrievalQA.from_chain_type(llm=llm, retriever=retriever)

def ask_bot(query: str) -> str:
    """
    Answers using strategy docs + enrich with live (snapshot) price and daily SMAs.
    Tickers must be referenced as $AAPL, $TSLA, etc.
    """
    # Normalize $AAPL -> AAPL for retrieval
    normalized_query = re.sub(r"\$([A-Z]{1,5})", r"\1", query)
    answer = qa.run(normalized_query)

    # Find $-prefixed tickers
    tickers = re.findall(r"\$[A-Z]{1,5}", query)

    for t in tickers:
        sym = t[1:]
        try:
            # Live intraday snapshot (safe)
            live = get_realtime_price_snapshot(sym)
            # Daily SMAs (historical only)
            _, smas = get_sma_and_last_price(sym)

            if live and live == live:
                answer += f"\n\n💡 {sym} current price: ${round(live,2)}."
            if smas:
                sma_text = ", ".join([f"SMA{l}={smas[l]}" for l in smas])
                answer += f" Key SMAs: {sma_text}."
                # Simple interpretation
                flags = []
                for l, v in smas.items():
                    if live and live > v:
                        flags.append(f"above SMA{l}")
                    elif live and live < v:
                        flags.append(f"below SMA{l}")
                    else:
                        flags.append(f"at SMA{l}")
                if flags:
                    answer += f" 📊 Trend check: price is " + "; ".join(flags) + "."
        except Exception as e:
            print(f"{sym} enrich fail: {e}")

    return answer
