
from uuid import uuid4

from app.embeddings import EmbeddingService
from app.ingestion import DocumentIngestionService
from app.vector_store import FaissVectorStore


embedding_service = EmbeddingService()
vector_store = FaissVectorStore(embedding_service)

ingestion_service = DocumentIngestionService(
    embedding_service=embedding_service,
    vector_store=vector_store,
)

document_id = uuid4()

chunk_count = ingestion_service.ingest_file(
    file_path="sample.txt",
    document_id=document_id,
)

print("Chunks stored:", chunk_count)

results = vector_store.similarity_search(
    "What is FastAPI?",
    k=2,
)

for document, score in results:
    print(f"Score: {score:.4f}")
    print(f"Content: {document.page_content}")
    print(f"Metadata: {document.metadata}")
    print()

# Test persistence by loading the saved index into a new store.
loaded_store = FaissVectorStore(embedding_service)
loaded_store.load("storage/faiss")

loaded_results = loaded_store.similarity_search(
    "What is FastAPI?",
    k=1,
)

print("Loaded index search:", loaded_results[0][0].page_content)
