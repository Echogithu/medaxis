"""Document upload and multimodal parsing endpoints.

POST   /api/v1/documents/upload       — Upload a file for parsing
GET    /api/v1/documents/{id}/result  — Poll for parse results
DELETE /api/v1/documents/{id}         — Delete a file and its result

All parsing is handled by LabReportParser (multimodal_parser.py) using
Kimi k2.5/k2.6 vision API for images and /v1/files for text documents.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserContext
from app.db.session import get_db
from app.models.document_parse import DocumentParseTask
from app.models.agent import AgentSession
from app.models.user import GuestSession
from app.services.document_router import (
    MAX_UPLOAD_SIZE,
    ParseMethod,
    classify_file,
    is_image_format,
    is_text_format,
)
from app.services.llm import get_llm_service
from app.services.multimodal_parser import LabReportParser

router = APIRouter()
logger = logging.getLogger(__name__)


def _generate_file_id(filename: str, user_id: str) -> str:
    """Generate a short unique file ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    name_hash = hashlib.sha256(f"{ts}{filename}{user_id}".encode()).hexdigest()[:12]
    return f"doc_{name_hash}"


async def _owned_parse_task(
    file_id: str, ctx: CurrentUserContext, db: AsyncSession
) -> DocumentParseTask:
    """只向有效的上传账号或访客会话返回解析任务。"""
    task = await db.get(DocumentParseTask, file_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Document '{file_id}' not found")

    if ctx.user is not None:
        if task.owner_user_id != ctx.user.id:
            raise HTTPException(status_code=404, detail=f"Document '{file_id}' not found")
    else:
        if not ctx.guest_id or task.owner_guest_id != uuid.UUID(ctx.guest_id):
            raise HTTPException(status_code=404, detail=f"Document '{file_id}' not found")
        guest = await db.get(GuestSession, task.owner_guest_id)
        if guest is None or guest.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail=f"Document '{file_id}' not found")
    return task


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    ctx: CurrentUserContext,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="Medical report file (image or document)"),
    session_id: str | None = Form(None),
) -> dict:
    """Upload a medical report file for multimodal parsing.

    Supported formats:
    - Images: jpeg, png, webp, gif (→ Kimi vision API)
    - Documents: pdf, doc, docx, txt, csv, md, ppt, pptx, xls, xlsx (→ Kimi /v1/files)

    Max file size: 10 MB.

    Returns a file_id for polling the parse result via GET /documents/{id}/result.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # Validate format
    try:
        parse_method = classify_file(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Read file bytes
    file_bytes = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {len(file_bytes)} bytes. Max: {MAX_UPLOAD_SIZE} bytes.",
        )

    owner_user_id = ctx.user.id if ctx.user else None
    try:
        owner_guest_id = uuid.UUID(ctx.guest_id) if ctx.user is None and ctx.guest_id else None
    except ValueError:
        owner_guest_id = None
    if owner_user_id is None and owner_guest_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if owner_guest_id is not None:
        guest = await db.get(GuestSession, owner_guest_id)
        if guest is None or guest.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Guest session has expired")

    safe_filename = PurePosixPath(file.filename.replace("\\", "/")).name[:255]
    file_id = _generate_file_id(safe_filename, str(owner_user_id or owner_guest_id))
    task = DocumentParseTask(
        file_id=file_id,
        filename=safe_filename,
        mime_type=file.content_type,
        parse_method=parse_method.value,
        status="queued",
        file_bytes=file_bytes,
        owner_user_id=owner_user_id,
        owner_guest_id=owner_guest_id,
        client_session_id=session_id or None,
    )
    db.add(task)
    await db.commit()

    from app.tasks.documents import process_document_parse

    try:
        process_document_parse.delay(file_id)
    except Exception as exc:
        task.status = "failed"
        task.error = "解析任务暂不可用，请稍后重试"
        await db.commit()
        logger.exception("Could not enqueue document parse file_id=%s", file_id)

    return {
        "file_id": file_id,
        "filename": safe_filename,
        "parse_method": parse_method.value,
        "status": task.status,
    }


@router.get("/{file_id}/result")
async def get_parse_result(
    file_id: str,
    ctx: CurrentUserContext,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poll for document parsing result.

    Returns:
        {"status": "processing"} — still parsing
        {"status": "completed", "result": LabReportResult} — done
        {"status": "failed", "error": "..."} — parsing failed
    """
    task = await _owned_parse_task(file_id, ctx, db)

    status_val = task.status
    response: dict[str, Any] = {"status": status_val, "file_id": file_id}

    if status_val == "completed":
        response["result"] = task.result
    elif status_val == "failed":
        response["error"] = task.error or "Unknown error"

    return response


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    file_id: str,
    ctx: CurrentUserContext,
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and its parse result."""
    task = await _owned_parse_task(file_id, ctx, db)
    if task.source_session_id is not None:
        source_session = await db.get(AgentSession, task.source_session_id)
        if source_session is not None:
            session_context = dict(source_session.context or {})
            session_context["lab_reports"] = [
                report for report in session_context.get("lab_reports", [])
                if str(report.get("file_id")) != task.file_id
            ]
            source_session.context = session_context
    await db.delete(task)
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Background parsing
# ---------------------------------------------------------------------------


async def _parse_image(db: AsyncSession, image_bytes: bytes, file_id: str) -> dict:
    """Parse an image via Kimi vision API."""
    llm = await get_llm_service(db, model_type="multimodal")
    parser = LabReportParser(llm)
    result = await parser.parse_image(image_bytes, file_id)
    return result.model_dump()


async def _parse_text_document(
    db: AsyncSession, file_bytes: bytes, filename: str, file_id: str
) -> dict:
    """Parse a text document via Kimi /v1/files file-extract + LLM structured extraction."""
    import io

    from openai import AsyncOpenAI

    # Get the multimodal provider config for file upload
    llm = await get_llm_service(db, model_type="multimodal")
    client = await llm._get_client()

    # Determine purpose based on file type
    from pathlib import Path
    ext = Path(filename).suffix.lower()

    # Upload to Kimi /v1/files
    file_obj = await asyncio.wait_for(
        client.files.create(
            file=(filename, io.BytesIO(file_bytes), "application/octet-stream"),
            purpose="file-extract",
        ),
        timeout=30.0,
    )

    try:
        # Extract content
        content_response = await client.files.content(file_id=file_obj.id)
        extracted_text = content_response.text

        # Use structured extraction LLM to parse the medical report
        extract_llm = await get_llm_service(db, model_type="structured_extraction")
        response = await extract_llm.chat(
            messages=[{
                "role": "user",
                "content": (
                    f"从以下医疗报告中提取所有检测指标为JSON数组格式：\n\n{extracted_text}\n\n"
                    "对每个指标输出JSON对象，包含：\n"
                    '- indicator_name: 指标的标准中文名称\n'
                    '- value: 检测数值（数字或文本）\n'
                    '- unit: 单位\n'
                    '- reference_range: 参考范围\n'
                    '- abnormal: 是否异常\n'
                    '- abnormal_direction: "high"或"low"\n'
                    '- confidence: 置信度(0.0-1.0)\n\n'
                    '返回格式：{"indicators": [...], "overall_confidence": 0.95}'
                ),
            }],
            max_tokens=4096,
        )

        # Parse the JSON response
        from app.services.multimodal_parser import LabReportParser, LabReportResult
        parser = LabReportParser(llm)  # reusing llm for normalization only
        indicators_raw = parser._extract_json_array(response.content)
        result = LabReportResult(file_id=file_id, raw_response=extracted_text)

        if indicators_raw:
            indicators = []
            total_conf = 0.0
            for item in indicators_raw:
                ind = parser._normalize_indicator(item)
                indicators.append(ind)
                total_conf += ind.confidence

            result.indicators = indicators
            if indicators:
                result.overall_confidence = round(total_conf / len(indicators), 2)
            result.requires_manual_review = result.overall_confidence < LabReportParser.CONFIDENCE_THRESHOLD
        else:
            result.error = "未能从文档中提取到检测指标"
            result.requires_manual_review = True

        return result.model_dump()

    finally:
        # Clean up file on Kimi servers
        try:
            await client.files.delete(file_id=file_obj.id)
        except Exception:
            pass
