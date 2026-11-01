import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

import faiss
import numpy as np
from langchain_core.documents import Document

from app.embeddings import EmbeddingService


class FaissVectorStore:
    """Store, persist, and search document embeddings using FAISS."""

    def __init__(self, embedding_service: EmbeddingService):
        self.embedding_service = embedding_service
        self.index: faiss.Index | None = None
        self.documents: list[Document] = []

    def add_documents(self, documents: list[Document]) -> None:
        """Embed and add document chunks to the current FAISS index."""
        if not documents:
            return

        texts = [document.page_content for document in documents]
        embeddings = self.embedding_service.embed_documents(texts)
        vectors = np.asarray(embeddings, dtype=np.float32)

        if self.index is None:
            self.index = faiss.IndexFlatIP(vectors.shape[1])

        if self.index.d != vectors.shape[1]:
            raise ValueError(
                "Embedding dimensions do not match the FAISS index."
            )

        self.index.add(vectors)
        self.documents.extend(documents)

    def add_documents_and_save(
        self,
        documents: list[Document],
        directory: str | Path,
    ) -> None:
        """Persist a candidate store before swapping it into live memory.

        The live in-memory index is unchanged if embedding, candidate
        construction, or persistence fails.
        """
        if not documents:
            return

        candidate_store = FaissVectorStore(
            embedding_service=self.embedding_service,
        )

        if self.index is not None:
            candidate_store.index = faiss.clone_index(self.index)

        candidate_store.documents = list(self.documents)
        candidate_store.add_documents(documents)

        # This commits the candidate snapshot before the live state changes.
        candidate_store.save(directory)

        self.index = candidate_store.index
        self.documents = candidate_store.documents

    def similarity_search(
        self,
        query: str,
        k: int = 4,
    ) -> list[tuple[Document, float]]:
        """Return the top-k matching documents and similarity scores."""
        if self.index is None or not self.documents or k <= 0:
            return []

        query_embedding = self.embedding_service.embed_query(query)
        query_vector = np.asarray(
            [query_embedding],
            dtype=np.float32,
        )

        k = min(k, len(self.documents))
        scores, indices = self.index.search(query_vector, k)

        results = []

        for score, document_index in zip(scores[0], indices[0]):
            if document_index == -1:
                continue

            results.append(
                (
                    self.documents[document_index],
                    float(score),
                )
            )

        return results

    def save(self, directory: str | Path) -> None:
        """Write a new immutable snapshot and atomically activate it.

        Snapshot files are written first. The active pointer is replaced
        only after the complete snapshot has been written.
        """
        if self.index is None:
            raise ValueError("Cannot save a store without a FAISS index.")

        if self.index.ntotal != len(self.documents):
            raise ValueError(
                "FAISS index vector count does not match stored documents."
            )

        directory = Path(directory)
        snapshots_directory = directory / "snapshots"

        directory.mkdir(parents=True, exist_ok=True)
        snapshots_directory.mkdir(parents=True, exist_ok=True)

        snapshot_id = str(uuid4())
        temporary_snapshot_directory = Path(
            tempfile.mkdtemp(
                prefix=".snapshot-tmp-",
                dir=snapshots_directory,
            )
        )
        final_snapshot_directory = snapshots_directory / snapshot_id

        active_pointer_path = directory / "active.json"
        temporary_pointer_path: Path | None = None

        try:
            index_path = temporary_snapshot_directory / "index.faiss"
            documents_path = temporary_snapshot_directory / "documents.json"

            # Write the index into the temporary snapshot directory.
            faiss.write_index(
                self.index,
                str(index_path),
            )

            # Flush the index file to disk.
            with index_path.open("rb") as index_file:
                os.fsync(index_file.fileno())

            documents_data = [
                {
                    "page_content": document.page_content,
                    "metadata": document.metadata,
                }
                for document in self.documents
            ]

            # Write and flush the corresponding document metadata.
            with documents_path.open(
                "w",
                encoding="utf-8",
            ) as documents_file:
                json.dump(
                    documents_data,
                    documents_file,
                    ensure_ascii=False,
                    indent=2,
                )
                documents_file.flush()
                os.fsync(documents_file.fileno())

            # Publish the complete snapshot directory.
            os.replace(
                temporary_snapshot_directory,
                final_snapshot_directory,
            )

            self._fsync_directory(snapshots_directory)

            # Prepare a new active pointer.
            pointer_data = {
                "snapshot_id": snapshot_id,
            }

            pointer_descriptor, pointer_temp_name = tempfile.mkstemp(
                prefix=".active-tmp-",
                dir=directory,
            )
            temporary_pointer_path = Path(pointer_temp_name)

            with os.fdopen(
                pointer_descriptor,
                "w",
                encoding="utf-8",
            ) as pointer_file:
                json.dump(pointer_data, pointer_file)
                pointer_file.flush()
                os.fsync(pointer_file.fileno())

            # This is the snapshot commit point.
            os.replace(
                temporary_pointer_path,
                active_pointer_path,
            )

            self._fsync_directory(directory)

        finally:
            # Clean up temporary artifacts if an operation failed.
            if temporary_snapshot_directory.exists():
                shutil.rmtree(
                    temporary_snapshot_directory,
                    ignore_errors=True,
                )

            if (
                temporary_pointer_path is not None
                and temporary_pointer_path.exists()
            ):
                temporary_pointer_path.unlink(missing_ok=True)

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        """Flush directory metadata where supported."""
        try:
            directory_descriptor = os.open(
                directory,
                os.O_RDONLY,
            )
        except OSError:
            return

        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

    def load(self, directory: str | Path) -> None:
        """Load the active snapshot, or load the legacy flat-file format."""
        directory = Path(directory)
        active_pointer_path = directory / "active.json"

        if active_pointer_path.exists():
            self._load_active_snapshot(
                directory,
                active_pointer_path,
            )
            return

        # Backward compatibility with the original flat-file layout.
        legacy_index_path = directory / "index.faiss"
        legacy_documents_path = directory / "documents.json"

        if (
            legacy_index_path.exists()
            and legacy_documents_path.exists()
        ):
            self._load_files(
                legacy_index_path,
                legacy_documents_path,
            )

            # Migrate the legacy data into the snapshot layout.
            self.save(directory)
            return

        raise FileNotFoundError(
            f"No active FAISS snapshot or legacy index found in {directory}"
        )

    def _load_active_snapshot(
        self,
        directory: Path,
        active_pointer_path: Path,
    ) -> None:
        """Resolve and load the snapshot referenced by active.json."""
        with active_pointer_path.open(
            "r",
            encoding="utf-8",
        ) as pointer_file:
            pointer_data = json.load(pointer_file)

        snapshot_id = pointer_data.get("snapshot_id")

        if not isinstance(snapshot_id, str):
            raise ValueError(
                "The active snapshot pointer has no valid snapshot ID."
            )

        # Validate the ID before using it as a directory name.
        try:
            snapshot_id = str(UUID(snapshot_id))
        except ValueError as exc:
            raise ValueError(
                "The active snapshot pointer contains an invalid snapshot ID."
            ) from exc

        snapshot_directory = directory / "snapshots" / snapshot_id

        index_path = snapshot_directory / "index.faiss"
        documents_path = snapshot_directory / "documents.json"

        if not index_path.exists() or not documents_path.exists():
            raise FileNotFoundError(
                f"Active snapshot {snapshot_id} is incomplete."
            )

        self._load_files(
            index_path,
            documents_path,
        )

    def _load_files(
        self,
        index_path: Path,
        documents_path: Path,
    ) -> None:
        """Load an index and its corresponding document metadata."""
        index = faiss.read_index(str(index_path))

        with documents_path.open(
            "r",
            encoding="utf-8",
        ) as documents_file:
            documents_data = json.load(documents_file)

        documents = [
            Document(
                page_content=item["page_content"],
                metadata=item["metadata"],
            )
            for item in documents_data
        ]

        if index.ntotal != len(documents):
            raise ValueError(
                "FAISS index vector count does not match stored documents."
            )

        self.index = index
        self.documents = documents

    def delete_document(
        self,
        document_id: str,
        directory: str | Path,
    ) -> bool:
        """Remove document chunks by committing a replacement snapshot."""
        document_id = str(document_id)

        remaining_documents = [
            document
            for document in self.documents
            if str(document.metadata.get("document_id")) != document_id
        ]

        if len(remaining_documents) == len(self.documents):
            return False

        if self.index is None:
            raise ValueError(
                "Cannot rebuild the vector store without an existing index."
            )

        replacement_store = FaissVectorStore(
            embedding_service=self.embedding_service,
        )

        if remaining_documents:
            # Rebuild the index from remaining documents.
            replacement_store.add_documents(remaining_documents)
        else:
            # Preserve the embedding dimension for an empty index.
            replacement_store.index = faiss.IndexFlatIP(self.index.d)
            replacement_store.documents = []

        # Persist and activate the replacement snapshot first.
        replacement_store.save(directory)

        # Only swap the in-memory state after persistence succeeds.
        self.index = replacement_store.index
        self.documents = replacement_store.documents

        return True