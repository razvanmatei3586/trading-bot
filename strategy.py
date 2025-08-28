# strategy.py (fast path)
import os
import re
from scanner import get_sma_and_last_price
from ibkr import get_realtime_price_snapshot
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import OllamaLLM
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

PERSIST_DIR = "strategy_db"

embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
llm = OllamaLLM(model="mistral")  # or your cfg

qa = None
if os.path.exists(PERSIST_DIR):
    db = Chroma(persist_directory=PERSIST_DIR, embedding_function=embeddings)
    retriever = db.as_retriever()
    print("📦 Loaded strategy index from disk")

    template = """You are a trading assistant.
RULES:
- Use only facts from the retrieved strategy documents AND the Live Metrics embedded inside the user’s question.
- If a detail is not in Live Metrics, say you don’t have it. Never invent numbers.
Context:
{context}

Question: {question}
Answer:"""
    prompt = PromptTemplate.from_template(template)
    qa = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        chain_type="stuff",
        chain_type_kwargs={"prompt": prompt},
    )
else:
    print("ℹ️ No strategy index found; run build_strategy_index.py to create one.")
    

def ask_bot(query: str) -> str:
    if not qa:
        return "⚠️ Strategy knowledge base not loaded. Run build_strategy_index.py first."

    # Extract $-tickers
    tickers = re.findall(r"\$[A-Z]{1,5}", query)
    live_lines = []
    for t in tickers:
        sym = t[1:]
        try:
            price = get_realtime_price_snapshot(sym)
            _, smas, _ = get_sma_and_last_price(sym)
            parts = []
            if price and price == price:  # not NaN
                parts.append(f"current_price={round(price,2)}")
            if smas:
                if 50 in smas: parts.append(f"SMA50={smas[50]}")
                if 100 in smas: parts.append(f"SMA100={smas[100]}")
                if 200 in smas: parts.append(f"SMA200={smas[200]}")
            if parts:
                live_lines.append(f"{sym}: " + ", ".join(parts))
        except Exception as e:
            print(f"{sym} metrics error: {e}")

    live_metrics_text = "\n".join(live_lines) if live_lines else "(none)"
    normalized = re.sub(r"\$([A-Z]{1,5})", r"\1", query)

    enriched_question = (
        f"Live Metrics:\n{live_metrics_text}\n\n"
        f"{normalized}"
    )

    try:
        res = qa.invoke({"query": enriched_question, "live_metrics": live_metrics_text})
        answer = res.get("result", "") if isinstance(res, dict) else str(res)
    except Exception as e:
        print(f"QA error: {e}")
        answer = "Note: strategy knowledge base unavailable right now."

    return answer
