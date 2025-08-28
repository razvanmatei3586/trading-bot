# build_strategy_index.py
import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import DirectoryLoader, TextLoader, PyPDFLoader

DOC_DIR = "strategy_docs"
PERSIST_DIR = "strategy_db"

def main():
    if not os.path.isdir(DOC_DIR):
        raise SystemExit(f"No {DOC_DIR}/ directory found")

    docs = []
    for pattern, loader_cls in [("**/*.txt", TextLoader), ("**/*.pdf", PyPDFLoader)]:
        loader = DirectoryLoader(DOC_DIR, glob=pattern, loader_cls=loader_cls)
        docs.extend(loader.load())
    print(f"📚 Loaded {len(docs)} docs")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = splitter.split_documents(docs)
    print(f"🔪 Split into {len(chunks)} chunks")

    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    db = Chroma.from_documents(chunks, embeddings, persist_directory=PERSIST_DIR)
    print(f"✅ Built index → {PERSIST_DIR}")

if __name__ == "__main__":
    main()
