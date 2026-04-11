"""
E-dem — HBF (Harcama Bildirim Formu) & Belgesiz Gelir/Gider
"""
import os
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi import status as http_status
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import (
    ExpenseReport, ExpenseItem, UndocumentedEntry,
    Request as ReqModel, User,
    EXPENSE_STATUSES, EXPENSE_STATUS_LABELS, EXPENSE_STATUS_COLORS,
    EXPENSE_PAYMENT_METHODS, EXPENSE_DOC_TYPES,
    _uuid, _now,
)
from templates_config import templates

router = APIRouter(prefix="/expenses", tags=["expenses"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads", "expenses")
ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _can_edit(report: ExpenseReport, user: User) -> bool:
    """Taslak ve reddedilen HBF'ler sahibi veya admin tarafından düzenlenebilir."""
    if user.role == "admin":
        return True
    return report.submitted_by == user.id and report.status in ("draft", "rejected")


def _can_approve(report: ExpenseReport, user: User) -> bool:
    """Admin veya referans sahibi (PM) onaylayabilir."""
    if user.role == "admin":
        return True
    if report.request and report.request.created_by == user.id:
        return True
    return False


# ---------------------------------------------------------------------------
# HBF Liste (referans bazlı)
# ---------------------------------------------------------------------------

@router.get("/request/{req_id}", response_class=HTMLResponse, name="expenses_list")
async def expenses_list(
    req_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)
    reports = req.expense_reports
    return templates.TemplateResponse("expenses/list.html", {
        "request": request,
        "current_user": current_user,
        "req": req,
        "reports": reports,
        "page_title": f"HBF — {req.request_no}",
        "STATUS_LABELS": EXPENSE_STATUS_LABELS,
        "STATUS_COLORS": EXPENSE_STATUS_COLORS,
    })


# ---------------------------------------------------------------------------
# Yeni HBF
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="expenses_new")
async def expenses_new(
    request: Request,
    request_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = None
    if request_id:
        req = db.query(ReqModel).filter(ReqModel.id == request_id).first()
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": None,
        "req": req,
        "page_title": "Yeni Harcama Bildirim Formu",
        "PAYMENT_METHODS": EXPENSE_PAYMENT_METHODS,
        "DOC_TYPES": EXPENSE_DOC_TYPES,
    })


@router.post("/new", name="expenses_create")
async def expenses_create(
    request: Request,
    request_id: str = Form(...),
    title: str = Form(""),
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import json
    req = db.query(ReqModel).filter(ReqModel.id == request_id).first()
    if not req:
        raise HTTPException(404)

    report = ExpenseReport(
        id=_uuid(),
        request_id=request_id,
        title=title.strip() or f"HBF — {req.request_no}",
        status="draft",
        submitted_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(report)
    db.flush()

    _save_items_from_json(db, report.id, items_json)
    db.commit()
    return RedirectResponse(url=f"/expenses/{report.id}/edit", status_code=302)


# ---------------------------------------------------------------------------
# HBF Düzenle
# ---------------------------------------------------------------------------

@router.get("/{report_id}/edit", response_class=HTMLResponse, name="expenses_edit")
async def expenses_edit_get(
    report_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": report,
        "req": report.request,
        "page_title": report.title or "HBF Düzenle",
        "PAYMENT_METHODS": EXPENSE_PAYMENT_METHODS,
        "DOC_TYPES": EXPENSE_DOC_TYPES,
    })


@router.post("/{report_id}/edit", name="expenses_edit_post")
async def expenses_edit_post(
    report_id: str,
    request: Request,
    title: str = Form(""),
    items_json: str = Form("[]"),
    next_action: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)

    report.title = title.strip() or report.title
    report.updated_at = _now()

    # Eski kalemleri sil, yenilerini ekle
    for item in list(report.items):
        db.delete(item)
    db.flush()
    _save_items_from_json(db, report.id, items_json)

    if next_action == "submit":
        report.status = "submitted"

    db.commit()

    if next_action == "submit":
        back_id = report.request_id
        return RedirectResponse(url=f"/requests/{back_id}", status_code=302)
    return RedirectResponse(url=f"/expenses/{report_id}/edit", status_code=302)


# ---------------------------------------------------------------------------
# HBF Görüntüle (onay sayfası)
# ---------------------------------------------------------------------------

@router.get("/{report_id}", response_class=HTMLResponse, name="expenses_view")
async def expenses_view(
    report_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": report,
        "req": report.request,
        "readonly": True,
        "can_approve": _can_approve(report, current_user),
        "page_title": report.title or "HBF Detay",
        "PAYMENT_METHODS": EXPENSE_PAYMENT_METHODS,
        "DOC_TYPES": EXPENSE_DOC_TYPES,
        "STATUS_LABELS": EXPENSE_STATUS_LABELS,
        "STATUS_COLORS": EXPENSE_STATUS_COLORS,
    })


# ---------------------------------------------------------------------------
# Onay / Red
# ---------------------------------------------------------------------------

@router.post("/{report_id}/approve", name="expenses_approve")
async def expenses_approve(
    report_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_approve(report, current_user):
        raise HTTPException(403)
    report.status = "approved"
    report.approved_by = current_user.id
    report.approved_at = _now()
    report.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{report.request_id}", status_code=302)


@router.post("/{report_id}/reject", name="expenses_reject")
async def expenses_reject(
    report_id: str,
    request: Request,
    rejection_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_approve(report, current_user):
        raise HTTPException(403)
    report.status = "rejected"
    report.rejection_note = rejection_note.strip()
    report.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{report.request_id}", status_code=302)


# ---------------------------------------------------------------------------
# Kalem belge yükleme
# ---------------------------------------------------------------------------

@router.post("/{report_id}/upload/{item_id}", name="expenses_upload_doc")
async def expenses_upload_doc(
    report_id: str,
    item_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)
    item = db.query(ExpenseItem).filter(
        ExpenseItem.id == item_id, ExpenseItem.report_id == report_id
    ).first()
    if not item:
        raise HTTPException(404)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        return JSONResponse({"ok": False, "error": "Desteklenmeyen dosya türü."}, status_code=400)

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return JSONResponse({"ok": False, "error": "Dosya 10 MB sınırını aşıyor."}, status_code=400)

    _ensure_upload_dir()
    safe_name = f"{item_id}{ext}"
    dest = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest, "wb") as f:
        f.write(content)

    item.document_path = f"expenses/{safe_name}"
    item.document_name = file.filename
    db.commit()
    return JSONResponse({"ok": True, "name": file.filename, "path": item.document_path})


@router.get("/doc/{item_id}", name="expenses_doc_download")
async def expenses_doc_download(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(ExpenseItem).filter(ExpenseItem.id == item_id).first()
    if not item or not item.document_path:
        raise HTTPException(404)
    path = os.path.join(os.path.dirname(__file__), "..", "static", "uploads", item.document_path)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, filename=item.document_name or "belge")


# ---------------------------------------------------------------------------
# Belgesiz Gelir/Gider (inline AJAX — request detail'den çağrılır)
# ---------------------------------------------------------------------------

undoc_router = APIRouter(prefix="/undocumented", tags=["undocumented"])


@undoc_router.post("/add", name="undocumented_add")
async def undocumented_add(
    request: Request,
    request_id: str = Form(...),
    entry_type: str = Form(...),    # gelir | gider
    description: str = Form(""),
    amount: float = Form(0.0),
    entry_date: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(ReqModel).filter(ReqModel.id == request_id).first()
    if not req:
        raise HTTPException(404)
    if entry_type not in ("gelir", "gider"):
        raise HTTPException(400)
    if amount <= 0:
        return JSONResponse({"ok": False, "error": "Tutar 0'dan büyük olmalı."}, status_code=400)

    entry = UndocumentedEntry(
        id=_uuid(),
        request_id=request_id,
        entry_type=entry_type,
        description=description.strip(),
        amount=round(amount, 2),
        entry_date=entry_date.strip(),
        created_by=current_user.id,
        created_at=_now(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return JSONResponse({
        "ok": True,
        "id": entry.id,
        "entry_type": entry.entry_type,
        "description": entry.description,
        "amount": entry.amount,
        "entry_date": entry.entry_date,
    })


@undoc_router.delete("/{entry_id}", name="undocumented_delete")
async def undocumented_delete(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(UndocumentedEntry).filter(UndocumentedEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404)
    # Sadece sahibi veya admin silebilir
    if current_user.role != "admin" and entry.created_by != current_user.id:
        raise HTTPException(403)
    db.delete(entry)
    db.commit()
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

def _save_items_from_json(db: Session, report_id: str, items_json: str):
    import json
    try:
        items = json.loads(items_json or "[]")
    except Exception:
        items = []
    for idx, it in enumerate(items):
        amount = float(it.get("amount", 0) or 0)
        vat_rate = float(it.get("vat_rate", 0) or 0)
        vat_amount = round(amount * vat_rate / 100, 2)
        total = round(amount + vat_amount, 2)
        item = ExpenseItem(
            id=_uuid(),
            report_id=report_id,
            item_date=it.get("item_date", "") or "",
            description=it.get("description", "") or "",
            payment_method=it.get("payment_method", "nakit"),
            document_type=it.get("document_type", "fis"),
            amount=round(amount, 2),
            vat_rate=vat_rate,
            vat_amount=vat_amount,
            total_amount=total,
            sort_order=idx,
            created_at=_now(),
        )
        db.add(item)
