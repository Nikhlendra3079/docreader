import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from app.db.database import get_db
from app.embeddings import EmbeddingService
from app.ingestion import DocumentIngestionService
from app.llm import get_chat_model
from app.models import (
    ChatMessage,
    ChatSession,
    Document as DocumentModel,
)
from app.rag_chain import build_rag_chain, stream_rag_chain
from app.schemas import QueryRequest, QueryResponse
from app.vector_store import FaissVectorStore
from app.auth.routes import router as auth_router
from app.auth.dependencies import get_current_user
from app.models.models import User


logger = logging.getLogger(__name__)

UPLOAD_DIRECTORY = Path("storage/uploads")
FAISS_DIRECTORY = Path("storage/faiss")
USER_FAISS_DIRECTORY = FAISS_DIRECTORY / "users"

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared embedding resources."""

    UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    USER_FAISS_DIRECTORY.mkdir(parents=True, exist_ok=True)

    embedding_service = EmbeddingService()

    app.state.embedding_service = embedding_service
    app.state.user_ingestion_services = {}

    logger.info("RAG resources initialized.")

    yield

    logger.info("RAG application shutting down.")

app = FastAPI(
    title="RAG API",
    description="Retrieval-Augmented Generation API",
    version="0.1.0",
    lifespan=lifespan,
)

def get_user_ingestion_service(
    request: Request,
    user_id: UUID,
) -> DocumentIngestionService:
    """Return the ingestion service for one user."""

    user_id = str(user_id)

    if not hasattr(request.app.state, "user_ingestion_services"):
        request.app.state.user_ingestion_services = {}

    services = request.app.state.user_ingestion_services

    if user_id in services:
        return services[user_id]

    index_directory = USER_FAISS_DIRECTORY / user_id

    vector_store = FaissVectorStore(
        embedding_service=request.app.state.embedding_service,
    )

    if (index_directory / "active.json").exists():
        vector_store.load(index_directory)

    ingestion_service = DocumentIngestionService(
        embedding_service=request.app.state.embedding_service,
        vector_store=vector_store,
        index_directory=index_directory,
    )

    services[user_id] = ingestion_service

    return ingestion_service

app.include_router(auth_router)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Document endpoints
# ---------------------------------------------------------------------------

@app.get("/documents")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List documents belonging to the authenticated user."""

    result = await db.execute(
        select(DocumentModel)
        .where(DocumentModel.user_id == current_user.id)
        .order_by(DocumentModel.uploaded_at.desc())
    )

    documents = result.scalars().all()

    return [
        {
            "document_id": str(document.id),
            "filename": document.filename,
            "status": document.status,
            "uploaded_at": document.uploaded_at,
            "error_message": document.error_message,
        }
        for document in documents
    ]


@app.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload, ingest, and index a document."""
    original_filename = Path(file.filename or "").name

    if not original_filename:
        raise HTTPException(
            status_code=400,
            detail="A filename is required.",
        )

    extension = Path(original_filename).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Upload a PDF, DOCX, or TXT file.",
        )

    document_id = uuid4()
    stored_path = UPLOAD_DIRECTORY / f"{document_id}{extension}"

    total_size = 0

    try:
        with stored_path.open("wb") as destination:
            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="File exceeds the 25 MB upload limit.",
                    )

                destination.write(chunk)

    except HTTPException:
        stored_path.unlink(missing_ok=True)
        raise

    finally:
        await file.close()

    if total_size == 0:
        stored_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty.",
        )

    document_record = DocumentModel(
        id=document_id,
        user_id=current_user.id,
        filename=original_filename,
        stored_path=str(stored_path),
        status="pending",
    )

    db.add(document_record)
    await db.commit()
    await db.refresh(document_record)

    try:
        ingestion_service = get_user_ingestion_service(
            request,
            current_user.id,
        )

        chunk_count = await run_in_threadpool(
            ingestion_service.ingest_file,
            stored_path,
            document_id,

)

        document_record.status = "completed"
        document_record.error_message = None

        await db.commit()

        return {
            "document_id": str(document_id),
            "filename": original_filename,
            "status": "completed",
            "chunks": chunk_count,
        }

    except Exception as exc:
        logger.exception(
            "Document ingestion failed for document %s",
            document_id,
        )

        document_record.status = "failed"
        document_record.error_message = str(exc)

        await db.commit()

        raise HTTPException(
            status_code=500,
            detail="Document ingestion failed.",
        ) from exc


@app.delete("/documents/{document_id}")
async def delete_document(
    document_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document from FAISS, disk, and PostgreSQL."""
    result = await db.execute(
        select(DocumentModel).where(
            DocumentModel.id == document_id,
            DocumentModel.user_id == current_user.id,
        )
    )

    document_record = result.scalar_one_or_none()

    if document_record is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    ingestion_service = get_user_ingestion_service(
        request,
        current_user.id,
    )

    vector_store = ingestion_service.vector_store

    try:
        # Remove this document's chunks and persist the updated FAISS index.
        chunks_removed = await run_in_threadpool(
            vector_store.delete_document,
            str(document_record.id),
            ingestion_service.index_directory,
        )

        # A completed document should have chunks in FAISS.
        # Don't silently delete its database record if they are missing.
        if not chunks_removed and document_record.status == "completed":
            raise HTTPException(
                status_code=500,
                detail="Document chunks were not found in the vector store.",
            )

        # Remove the original uploaded file.
        stored_path = Path(document_record.stored_path)
        stored_path.unlink(missing_ok=True)

        # Remove the PostgreSQL record.
        await db.delete(document_record)
        await db.commit()

        return {
            "document_id": str(document_id),
            "filename": document_record.filename,
            "status": "deleted",
        }

    except HTTPException:
        raise

    except Exception as exc:
        await db.rollback()

        logger.exception(
            "Failed to delete document %s",
            document_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to delete document.",
        ) from exc


# ---------------------------------------------------------------------------
# Chat session endpoints
# ---------------------------------------------------------------------------

@app.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List conversations, ordered by most recent activity."""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(
            ChatSession.updated_at.desc(),
            ChatSession.created_at.desc(),
        )
    )

    sessions = result.scalars().all()

    return [
        {
            "session_id": str(chat_session.id),
            "title": chat_session.title,
            "created_at": chat_session.created_at,
            "updated_at": chat_session.updated_at,
        }
        for chat_session in sessions
    ]


@app.get("/sessions/{session_id}")
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a conversation and its messages."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id
            
        )
    )

    chat_session = result.scalar_one_or_none()

    if chat_session is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    messages_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == chat_session.id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )

    messages = messages_result.scalars().all()

    return {
        "session_id": str(chat_session.id),
        "title": chat_session.title,
        "created_at": chat_session.created_at,
        "updated_at": chat_session.updated_at,
        "messages": [
            {
                "message_id": str(message.id),
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }


@app.delete("/sessions/{session_id}")
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),

):
    """Delete a conversation and its messages.

    Uploaded documents and the FAISS vector index are not affected.
    """
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )

    chat_session = result.scalar_one_or_none()

    if chat_session is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    try:
        # Delete messages explicitly to avoid implicit async relationship loading.
        await db.execute(
            delete(ChatMessage).where(
                ChatMessage.session_id == chat_session.id
            )
        )

        await db.delete(chat_session)
        await db.commit()

        return {
            "session_id": str(session_id),
            "status": "deleted",
        }

    except Exception as exc:
        await db.rollback()

        logger.exception(
            "Failed to delete conversation %s",
            session_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to delete conversation.",
        ) from exc


# ---------------------------------------------------------------------------
# RAG query endpoint
# ---------------------------------------------------------------------------

@app.post("/query", response_model=QueryResponse)
async def query_documents(
    request: Request,
    payload: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve relevant document chunks and generate an answer."""
    question = payload.question.strip()

    if not question:
        raise HTTPException(
            status_code=422,
            detail="Question cannot be empty.",
        )

    ingestion_service = get_user_ingestion_service(
        request,
        current_user.id,
    )

    vector_store = ingestion_service.vector_store

    if vector_store.index is None or not vector_store.documents:
        raise HTTPException(
            status_code=400,
            detail="No documents have been uploaded yet.",
        )

    # Retrieve the existing conversation or create a new one.
    chat_history = []

    if payload.session_id is not None:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == payload.session_id,
                ChatSession.user_id == current_user.id
            )
        )

        chat_session = result.scalar_one_or_none()

        if chat_session is None:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found.",
            )

        # Load previous messages before saving the current question.
        history_result = await db.execute(
            select(ChatMessage.role, ChatMessage.content)
            .where(ChatMessage.session_id == chat_session.id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )

        # Convert database messages into LangChain message objects.
        chat_history = [
            HumanMessage(content=content)
            if role == "user"
            else AIMessage(content=content)
            for role, content in history_result.all()
        ]

    else:
        chat_session = ChatSession(
            user_id=current_user.id,
            title=question[:255],
        )

        db.add(chat_session)
        await db.commit()
        await db.refresh(chat_session)

    # Persist the current user's question for both new and existing sessions.
    user_message = ChatMessage(
        session_id=chat_session.id,
        role="user",
        content=question,
    )

    db.add(user_message)

    # Update the session's activity timestamp.
    chat_session.updated_at = datetime.now(timezone.utc)

    await db.commit()

    try:
        llm = get_chat_model(payload.provider)

        # Our custom FAISS store returns (Document, score) pairs.
        # The LCEL chain expects a retriever that returns Documents.
        retrieved_documents = []

        def retrieve_documents(query: str):
            """Retrieve documents and retain them for the API response."""
            nonlocal retrieved_documents

            retrieved_documents = [
                document
                for document, score in vector_store.similarity_search(
                    query,
                    k=4,
                )
            ]

            return retrieved_documents


        retriever = RunnableLambda(retrieve_documents)

        chain = build_rag_chain(
            retriever=retriever,
            llm=llm,
        )

        answer = await run_in_threadpool(
            chain.invoke,
            {
                "question": question,
                "chat_history": chat_history,
            },
        )

        sources = [
            {
                "filename": document.metadata.get("source", "Unknown"),
                "chunk_index": document.metadata.get("chunk_index", -1),
                "content": document.page_content,
            }
            for document in retrieved_documents
        ]

        assistant_message = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content=answer,
        )

        db.add(assistant_message)

        # Refresh activity timestamp after the assistant responds.
        chat_session.updated_at = datetime.now(timezone.utc)

        await db.commit()

        return QueryResponse(
            session_id=chat_session.id,
            response=answer,
            sources=sources,
        )

    except Exception as exc:
        await db.rollback()

        logger.exception(
            "Query generation failed for session %s",
            chat_session.id,
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to generate an answer.",
        ) from exc


@app.post("/query/stream")
async def query_documents_stream(
    request: Request,
    payload: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream a Normal Chat or RAG answer as Server-Sent Events."""
    question = payload.question.strip()

    if not question:
        raise HTTPException(
            status_code=422,
            detail="Question cannot be empty.",
        )

    ingestion_service = get_user_ingestion_service(
        request,
        current_user.id,
    )

    vector_store = ingestion_service.vector_store

    # Only RAG mode requires an indexed document collection.
    if payload.mode == "rag" and (
        vector_store.index is None or not vector_store.documents
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "No documents have been uploaded yet. "
                "Upload a document or switch to Normal Chat."
            ),
        )

    # Retrieve an existing conversation or create a new one.
    chat_history = []

    if payload.session_id is not None:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == payload.session_id,
                ChatSession.user_id == current_user.id,
            )
        )

        chat_session = result.scalar_one_or_none()

        if chat_session is None:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found.",
            )

        history_result = await db.execute(
            select(ChatMessage.role, ChatMessage.content)
            .where(ChatMessage.session_id == chat_session.id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )

        chat_history = [
            HumanMessage(content=content)
            if role == "user"
            else AIMessage(content=content)
            for role, content in history_result.all()
        ]

    else:
        chat_session = ChatSession(
            title=question[:255],
        )

        db.add(chat_session)
        await db.commit()
        await db.refresh(chat_session)

    # Persist the user's question before generation starts.
    user_message = ChatMessage(
        session_id=chat_session.id,
        role="user",
        content=question,
    )

    db.add(user_message)
    chat_session.updated_at = datetime.now(timezone.utc)
    await db.commit()

    session_id = chat_session.id
    retrieved_documents = []

    # RAG's retriever is defined here but only called in RAG mode.
    def retrieve_documents(query: str):
        nonlocal retrieved_documents

        retrieved_documents = [
            document
            for document, score in vector_store.similarity_search(
                query,
                k=4,
            )
        ]

        return retrieved_documents

    retriever = RunnableLambda(retrieve_documents)

    try:
        llm = get_chat_model(payload.provider)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    async def event_generator():
        answer_parts = []

        def encode_event(event_name: str, data: dict) -> str:
            return (
                f"event: {event_name}\n"
                f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            )

        try:
            if payload.mode == "rag":
                # Existing RAG chain: preserve retrieval, query rewriting,
                # and grounded response behavior.
                async for token in stream_rag_chain(
                    {
                        "question": question,
                        "chat_history": chat_history,
                    },
                    retriever=retriever,
                    llm=llm,
                ):
                    answer_parts.append(token)
                    yield encode_event("token", {"text": token})

            else:
                # Normal Chat sends conversation history directly to the model.
                messages = [
                    *chat_history,
                    HumanMessage(content=question),
                ]

                async for chunk in llm.astream(messages):
                    content = chunk.content

                    if isinstance(content, str):
                        token = content
                    elif isinstance(content, list):
                        token = "".join(
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict)
                        )
                    else:
                        token = ""

                    if not token:
                        continue

                    answer_parts.append(token)
                    yield encode_event("token", {"text": token})

            # Persist the assistant answer after successful generation.
            answer = "".join(answer_parts)

            assistant_message = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=answer,
            )

            db.add(assistant_message)
            chat_session.updated_at = datetime.now(timezone.utc)
            await db.commit()

            # Only RAG mode has source chunks.
            sources = [
                {
                    "filename": document.metadata.get(
                        "source",
                        "Unknown",
                    ),
                    "chunk_index": document.metadata.get(
                        "chunk_index",
                        -1,
                    ),
                    "content": document.page_content,
                }
                for document in retrieved_documents
            ] if payload.mode == "rag" else []

            yield encode_event("sources", {"sources": sources})
            yield encode_event(
                "done",
                {"session_id": str(session_id)},
            )

        except Exception:
            await db.rollback()

            logger.exception(
                "Streaming query failed for session %s",
                session_id,
            )

            yield encode_event(
                "error",
                {"message": "Failed to generate an answer."},
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


@app.patch("/sessions/{session_id}")
async def rename_session(
    session_id: UUID,
    payload: RenameSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rename an existing conversation."""
    title = payload.title.strip()

    if not title:
        raise HTTPException(
            status_code=422,
            detail="Conversation title cannot be empty.",
        )

    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )

    chat_session = result.scalar_one_or_none()

    if chat_session is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    try:
        chat_session.title = title
        chat_session.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(chat_session)

        return {
            "session_id": str(chat_session.id),
            "title": chat_session.title,
            "created_at": chat_session.created_at,
            "updated_at": chat_session.updated_at,
        }

    except Exception as exc:
        await db.rollback()

        logger.exception(
            "Failed to rename conversation %s",
            session_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to rename conversation.",
        ) from exc
