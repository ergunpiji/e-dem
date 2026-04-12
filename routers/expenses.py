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
# GET /expenses  — Genel HBF Listesi (tüm referanslar)
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="expenses_all_list")
async def expenses_all_list(
    request: Request,
    status_filter: str = "all",  # all | draft | submitted | approved | rejected
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ExpenseReport)

    # PM sadece kendi referanslarına ait HBF'leri görür
    if current_user.role in ("yonetici", "asistan"):
        query = query.join(ExpenseReport.request).filter(
            ReqModel.created_by == current_user.id
        )
    # e_dem sadece kendi gönderdiği HBF'leri görür
    elif current_user.role == "e_dem":
        query = query.filter(ExpenseReport.submitted_by == current_user.id)

    if status_filter != "all":
        query = query.filter(ExpenseReport.status == status_filter)

    reports = query.order_by(ExpenseReport.created_at.desc()).all()

    # Onay bekleyen sayısı
    pending_q = db.query(ExpenseReport).filter(ExpenseReport.status == "submitted")
    if current_user.role in ("yonetici", "asistan"):
        pending_q = pending_q.join(ExpenseReport.request).filter(
            ReqModel.created_by == current_user.id
        )
    elif current_user.role == "e_dem":
        pending_q = pending_q.filter(ExpenseReport.submitted_by == current_user.id)
    pending_count = pending_q.count()

    return templates.TemplateResponse("expenses/list_all.html", {
        "request":       request,
        "current_user":  current_user,
        "page_title":    "Harcama Formları (HBF)",
        "reports":       reports,
        "status_filter": status_filter,
        "pending_count": pending_count,
        "STATUS_LABELS": EXPENSE_STATUS_LABELS,
        "STATUS_COLORS": EXPENSE_STATUS_COLORS,
        "STATUSES":      EXPENSE_STATUSES,
    })


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

def _all_requests_for_user(db: Session, user):
    """Form dropdown için tüm aktif referansları döndür (role'e göre filtrele)."""
    from models import Request as ReqModel
    q = db.query(ReqModel).filter(ReqModel.status.notin_(["cancelled", "closing", "closed"]))
    if user.role in ("yonetici", "asistan", "mudur"):
        q = q.filter(ReqModel.created_by == user.id)
    return q.order_by(ReqModel.created_at.desc()).all()


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
    all_reqs = _all_requests_for_user(db, current_user)
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": None,
        "req": req,
        "all_requests": all_reqs,
        "page_title": "Yeni Harcama Bildirim Formu",
        "PAYMENT_METHODS": EXPENSE_PAYMENT_METHODS,
        "DOC_TYPES": EXPENSE_DOC_TYPES,
    })


@router.post("/new", name="expenses_create")
async def expenses_create(
    request: Request,
    request_ids_json: str = Form("[]"),
    title: str = Form(""),
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import json
    try:
        refs = json.loads(request_ids_json or "[]")
    except Exception:
        refs = []
    if not refs:
        raise HTTPException(400, detail="En az bir referans seçmelisiniz.")

    try:
        items = json.loads(items_json or "[]")
    except Exception:
        items = []

    primary_id = refs[0]["id"]
    refs_by_id = {r["id"]: r for r in refs}

    # Kalemleri assigned_request_id'ye göre grupla
    # Atanmamış kalemler birincil referansa gider
    groups: dict[str, list] = {}
    for item in items:
        rid = item.get("assigned_request_id") or primary_id
        if rid not in refs_by_id:
            rid = primary_id   # geçersiz ref → birincile düş
        groups.setdefault(rid, []).append(item)

    if not groups:
        groups[primary_id] = []

    first_report_id = None
    for ref_id, group_items in groups.items():
        req_obj = db.query(ReqModel).filter(ReqModel.id == ref_id).first()
        if not req_obj:
            continue
        ref_no = refs_by_id.get(ref_id, {}).get("request_no", ref_id[:8])
        report_title = (title.strip() or f"HBF — {req_obj.request_no}")
        if len(groups) > 1:
            report_title = f"{report_title} ({ref_no})"
        report = ExpenseReport(
            id=_uuid(),
            request_id=ref_id,
            request_ids_json=json.dumps(refs, ensure_ascii=False),
            title=report_title,
            status="draft",
            submitted_by=current_user.id,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(report)
        db.flush()
        _save_items_from_json(db, report.id, json.dumps(group_items))
        if first_report_id is None:
            first_report_id = report.id

    db.commit()
    return RedirectResponse(url=f"/expenses/{first_report_id}/edit", status_code=302)


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
    all_reqs = _all_requests_for_user(db, current_user)
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": report,
        "req": report.request,
        "all_requests": all_reqs,
        "page_title": report.title or "HBF Düzenle",
        "PAYMENT_METHODS": EXPENSE_PAYMENT_METHODS,
        "DOC_TYPES": EXPENSE_DOC_TYPES,
    })


@router.post("/{report_id}/edit", name="expenses_edit_post")
async def expenses_edit_post(
    report_id: str,
    request: Request,
    title: str = Form(""),
    request_ids_json: str = Form("[]"),
    items_json: str = Form("[]"),
    next_action: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import json as _json
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)

    report.title = title.strip() or report.title
    report.updated_at = _now()

    try:
        refs = _json.loads(request_ids_json or "[]")
    except Exception:
        refs = []
    if refs:
        report.request_ids_json = _json.dumps(refs, ensure_ascii=False)

    # Edit modunda sadece bu raporun kalemlerini güncelle (split yok)
    for item in list(report.items):
        db.delete(item)
    db.flush()
    _save_items_from_json(db, report.id, items_json)

    if next_action == "submit":
        report.status = "submitted"

    db.commit()

    if next_action == "submit":
        back_id = report.request_id
        # Bildirim: PM onayı bekleniyor
        req_obj = db.query(ReqModel).filter(ReqModel.id == back_id).first() if back_id else None
        if req_obj and req_obj.created_by:
            from utils.notifications import create_notification
            create_notification(
                db,
                user_id    = req_obj.created_by,
                notif_type = "hbf_submitted",
                title      = f"HBF onayı bekleniyor — {report.title or 'Harcama Formu'}",
                message    = f"{req_obj.request_no} referansına ait harcama formu onayınızı bekliyor.",
                link       = f"/expenses/{report.id}",
                ref_id     = report.id,
            )
            db.commit()
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
        "all_requests": [],
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

@router.post("/{report_id}/sync-rows", name="expenses_sync_rows")
async def expenses_sync_rows(
    report_id: str,
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Satırları kaydet ve item ID'lerini döndür (belge yükleme öncesi auto-save)."""
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)

    for item in list(report.items):
        db.delete(item)
    db.flush()
    _save_items_from_json(db, report_id, items_json)
    db.commit()
    db.refresh(report)

    return JSONResponse({
        "ok": True,
        "items": [{"idx": i, "id": item.id} for i, item in enumerate(
            sorted(report.items, key=lambda x: x.sort_order)
        )],
    })


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
    if current_user.role not in ("admin", "muhasebe_muduru", "muhasebe"):
        raise HTTPException(403, detail="Bu işlem için yetkiniz yok.")
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
    # Sadece muhasebe rolü veya admin silebilir
    if current_user.role not in ("admin", "muhasebe_muduru", "muhasebe"):
        raise HTTPException(403, detail="Bu işlem için yetkiniz yok.")
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
            assigned_request_id=it.get("assigned_request_id") or None,
            item_date=it.get("item_date", "") or "",
            description=it.get("description", "") or "",
            payment_method=it.get("payment_method", "nakit"),
            document_type=it.get("document_type", "fis"),
            amount=round(amount, 2),
            vat_rate=vat_rate,
            vat_amount=vat_amount,
            total_amount=total,
            sort_order=idx,
            # Daha önce yüklenen belgeyi koru
            document_path=it.get("document_path") or None,
            document_name=it.get("document_name") or None,
            created_at=_now(),
        )
        db.add(item)
