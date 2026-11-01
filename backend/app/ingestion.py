from pathlib import Path
from uuid import UUID

import docx2txt
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.embeddings import EmbeddingService
from app.vector_store import FaissVectorStore


class DocumentIngestionService:
    """Extract, chunk, embed, and store uploaded documents."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: FaissVectorStore,
        index_directory: str | Path = "storage/faiss",
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.index_directory = Path(index_directory)

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
            add_start_index=True,
        )

    def extract_text(self, file_path: str | Path) -> str:
        """Extract text from a supported file."""
        file_path = Path(file_path)
        extension = file_path.suffix.lower()

        if extension not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {extension}. "
                f"Supported types: {', '.join(sorted(self.SUPPORTED_EXTENSIONS))}"
            )

        if extension == ".txt":
            return file_path.read_text(encoding="utf-8")

        if extension == ".docx":
            return docx2txt.process(str(file_path))

        if extension == ".pdf":
            reader = PdfReader(str(file_path))
            pages = [
                page.extract_text() or ""
                for page in reader.pages
            ]
            return "\n\n".join(pages)

        raise ValueError(f"Unsupported file type: {extension}")

    def ingest_file(
        self,
        file_path: str | Path,
        document_id: UUID,
    ) -> int:
        """Process a file and return the number of stored chunks."""
        file_path = Path(file_path)
        text = self.extract_text(file_path)

        if not text.strip():
            raise ValueError(
                "The uploaded file contains no extractable text."
            )

        source_document = Document(
            page_content=text,
            metadata={
                "document_id": str(document_id),
                "source": file_path.name,
            },
        )

        documents = self.text_splitter.split_documents(
            [source_document]
        )

        for index, document in enumerate(documents):
            document.metadata["chunk_index"] = index

        # Build and persist a candidate index before updating the live store.
        self.vector_store.add_documents_and_save(
            documents,
            self.index_directory,
        )

        return len(documents)