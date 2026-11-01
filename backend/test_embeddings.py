from app.embeddings import EmbeddingService

embedding_service = EmbeddingService()

document_vectors = embedding_service.embed_documents(
    [
        "FastAPI is a Python web framework.",
        "PostgreSQL is a relational database.",
    ]
)

query_vector = embedding_service.embed_query(
    "What is FastAPI?"
)

print("Document count:", len(document_vectors))
print("Embedding dimensions:", len(document_vectors[0]))
print("Query dimensions:", len(query_vector))