
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db.database import get_db
from app.models import Document

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_DIRECTORY = Path("storage/uploads")
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


async def save_upload(upload: UploadFile, destination: Path) -> int:
    """Save an upload in chunks and enforce the maximum file size."""
    total_size = 0

    try:
        with destination.open("wb") as file:
            while chunk := await upload.read(1024 * 1024):
                total_size += len(chunk)

                if total_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="File exceeds the 20 MB upload limit.",
                    )

                file.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    if total_size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    return total_size


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    upload: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    """Upload, ingest, and index a document."""
    original_filename = Path(upload.filename or "").name
    extension = Path(original_filename).suffix.lower()

    if not original_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A filename is required.",
        )

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Supported file types are PDF, DOCX, and TXT.",
        )

    UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)

    document_id = uuid4()
    stored_path = UPLOAD_DIRECTORY / f"{document_id}{extension}"

    await save_upload(upload, stored_path)

    document = Document(
        id=document_id,
        filename=original_filename,
        stored_path=str(stored_path),
        status="pending",
    )

    db.add(document)
    await db.commit()

    try:
        ingestion_service = request.app.state.ingestion_service

        chunk_count = await run_in_threadpool(
            ingestion_service.ingest_file,
            stored_path,
            document_id,
        )

        document.status = "completed"
        document.error_message = None
        await db.commit()

        return {
            "document_id": str(document.id),
            "filename": document.filename,
            "status": document.status,
            "chunks_created": chunk_count,
        }

    except Exception:
        logger.exception(
            "Ingestion failed for document %s",
            document_id,
        )

        document.status = "failed"
        document.error_message = "Document ingestion failed."
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Document ingestion failed. "
                "The document status has been marked as failed."
            ),
        )
