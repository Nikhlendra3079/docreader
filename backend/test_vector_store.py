from langchain_core.documents import Document

from app.embeddings import EmbeddingService
from app.vector_store import FaissVectorStore


embedding_service = EmbeddingService()
vector_store = FaissVectorStore(embedding_service)

documents = [
    Document(
        page_content="FastAPI is a modern Python web framework.",
        metadata={"source": "fastapi.txt"},
    ),
    Document(
        page_content="PostgreSQL is an open-source relational database.",
        metadata={"source": "postgresql.txt"},
    ),
    Document(
        page_content="FAISS is a library for efficient similarity search.",
        metadata={"source": "faiss.txt"},
    ),
]

vector_store.add_documents(documents)

results = vector_store.similarity_search(
    "What is FastAPI?",
    k=2,
)

for document, score in results:
    print(f"Score: {score:.4f}")
    print(f"Content: {document.page_content}")
    print(f"Metadata: {document.metadata}")
    print()