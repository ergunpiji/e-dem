"""
E-dem — Kütüphane router
Referans başına notlar, belgeler ve aktivite logu yönetimi.
"""
import os
import shutil

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, Request as FastReq
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import (
    Request as ReqModel, RequestNote, RequestDocument, ActivityLog,
    User, REQUEST_DOCUMENT_TYPES
)
from templates_config import templates

router = APIRouter(prefix="/requests", tags=["library"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads", "library")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Yardımcı — aktivite kaydı (diğer router'lardan da çağrılır)
# ---------------------------------------------------------------------------

def log_activity(
    db: Session,
    request_id: str,
    event_type: str,
    title: str,
    detail: str = "",
    user_id: str | None = None,
) -> ActivityLog:
    """Referansa aktivite logu ekler ve kaydeder."""
    entry = ActivityLog(
        request_id=request_id,
        user_id=user_id,
        event_type=event_type,
        title=title,
        detail=detail,
    )
    db.add(entry)
    db.flush()   # commit'i çağırana bırak
    return entry


# ---------------------------------------------------------------------------
# Not ekle
# ---------------------------------------------------------------------------

@router.post("/{req_id}/notes", name="library_add_note")
async def add_note(
    req_id: str,
    content: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    content = content.strip()
    if not content:
        raise HTTPException(400, "Not boş olamaz")

    note = RequestNote(
        request_id=req_id,
        created_by=current_user.id,
        content=content,
    )
    db.add(note)

    log_activity(
        db, req_id, "note_added",
        f"{current_user.full_name} not ekledi",
        content[:120] + ("…" if len(content) > 120 else ""),
        user_id=current_user.id,
    )
    db.commit()
    return RedirectResponse(f"/requests/{req_id}#tab-library", status_code=303)


# ---------------------------------------------------------------------------
# Not sil
# ---------------------------------------------------------------------------

@router.post("/{req_id}/notes/{note_id}/delete", name="library_delete_note")
async def delete_note(
    req_id: str,
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = db.query(RequestNote).filter(
        RequestNote.id == note_id,
        RequestNote.request_id == req_id,
    ).first()
    if not note:
        raise HTTPException(404)

    # Sadece yazan veya admin/müdür silebilir
    if note.created_by != current_user.id and current_user.role not in ("admin", "mudur"):
        raise HTTPException(403)

    db.delete(note)
    db.commit()
    return RedirectResponse(f"/requests/{req_id}#tab-library", status_code=303)


# ---------------------------------------------------------------------------
# Belge yükle
# ---------------------------------------------------------------------------

@router.post("/{req_id}/documents", name="library_upload_document")
async def upload_document(
    req_id: str,
    doc_name: str = Form(""),
    doc_type: str = Form("diger"),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    # Dosya adı güvenliğini sağla
    from uuid import uuid4
    ext = os.path.splitext(file.filename or "")[1].lower()
    safe_name = f"{uuid4().hex}{ext}"
    dest_dir = os.path.join(UPLOAD_DIR, req_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, safe_name)

    size = 0
    with open(dest_path, "wb") as f:
        chunk = await file.read(1024 * 1024)
        while chunk:
            f.write(chunk)
            size += len(chunk)
            chunk = await file.read(1024 * 1024)

    rel_path = f"uploads/library/{req_id}/{safe_name}"
    label = doc_name.strip() or file.filename or safe_name

    doc = RequestDocument(
        request_id=req_id,
        uploaded_by=current_user.id,
        doc_type=doc_type,
        doc_name=label,
        file_path=rel_path,
        file_name=file.filename or safe_name,
        file_size=size,
    )
    db.add(doc)

    from models import REQUEST_DOCUMENT_TYPE_LABELS
    type_label = REQUEST_DOCUMENT_TYPE_LABELS.get(doc_type, doc_type)
    log_activity(
        db, req_id, "document_added",
        f"{current_user.full_name} belge yükledi",
        f"{type_label}: {label}",
        user_id=current_user.id,
    )
    db.commit()
    return RedirectResponse(f"/requests/{req_id}#tab-library", status_code=303)


# ---------------------------------------------------------------------------
# Belge sil
# ---------------------------------------------------------------------------

@router.post("/{req_id}/documents/{doc_id}/delete", name="library_delete_document")
async def delete_document(
    req_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(RequestDocument).filter(
        RequestDocument.id == doc_id,
        RequestDocument.request_id == req_id,
    ).first()
    if not doc:
        raise HTTPException(404)

    if doc.uploaded_by != current_user.id and current_user.role not in ("admin", "mudur"):
        raise HTTPException(403)

    # Disk dosyasını sil
    disk_path = os.path.join(os.path.dirname(__file__), "..", "static", doc.file_path)
    try:
        if os.path.isfile(disk_path):
            os.remove(disk_path)
    except Exception:
        pass

    log_activity(
        db, req_id, "document_removed",
        f"{current_user.full_name} belge sildi",
        doc.doc_name,
        user_id=current_user.id,
    )
    db.delete(doc)
    db.commit()
    return RedirectResponse(f"/requests/{req_id}#tab-library", status_code=303)


# ---------------------------------------------------------------------------
# Belge indir
# ---------------------------------------------------------------------------

@router.get("/{req_id}/documents/{doc_id}/download", name="library_download_document")
async def download_document(
    req_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(RequestDocument).filter(
        RequestDocument.id == doc_id,
        RequestDocument.request_id == req_id,
    ).first()
    if not doc:
        raise HTTPException(404)

    disk_path = os.path.join(os.path.dirname(__file__), "..", "static", doc.file_path)
    if not os.path.isfile(disk_path):
        raise HTTPException(404, "Dosya bulunamadı")

    return FileResponse(
        disk_path,
        filename=doc.file_name,
        media_type="application/octet-stream",
    )
