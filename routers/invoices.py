"""
E-dem — Fatura Yönetimi
Erişim: admin, muhasebe_muduru, muhasebe
"""
import os
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Invoice, INVOICE_TYPES, Request as ReqModel, User, _uuid, _now
from templates_config import templates

router = APIRouter(prefix="/invoices", tags=["invoices"])

FINANCE_ROLES = {"admin", "muhasebe_muduru", "muhasebe"}
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads", "invoices")
ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _require_finance(current_user: User):
    if current_user.role not in FINANCE_ROLES:
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")


def _get_invoice_or_404(db: Session, invoice_id: str) -> Invoice:
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura bulunamadı.")
    return inv


def _save_document(file: UploadFile, invoice_id: str) -> tuple[str, str]:
    """Dosyayı kaydet, (relative_path, original_name) döner."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="Desteklenmeyen dosya türü. PDF veya resim yükleyin.")
    dest_filename = f"{invoice_id}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, dest_filename)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    # Check size
    if os.path.getsize(dest_path) > MAX_FILE_SIZE:
        os.remove(dest_path)
        raise HTTPException(status_code=400, detail="Dosya boyutu 10 MB'ı aşamaz.")
    return f"uploads/invoices/{dest_filename}", file.filename or dest_filename


# ---------------------------------------------------------------------------
# GET /invoices/new  — fatura oluştur formu
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="invoices_new_form")
async def invoices_new_form(
    request: Request,
    request_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)
    req = None
    if request_id:
        req = db.query(ReqModel).filter(ReqModel.id == request_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Referans bulunamadı.")
    all_requests = db.query(ReqModel).order_by(ReqModel.created_at.desc()).all()
    return templates.TemplateResponse("invoices/form.html", {
        "request":       request,
        "current_user":  current_user,
        "page_title":    "Yeni Fatura",
        "invoice":       None,
        "selected_req":  req,
        "all_requests":  all_requests,
        "invoice_types": INVOICE_TYPES,
        "edit_mode":     False,
    })


# ---------------------------------------------------------------------------
# POST /invoices/new  — fatura kaydet
# ---------------------------------------------------------------------------

@router.post("/new", name="invoices_create")
async def invoices_create(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    req_id:       str = Form(...),
    invoice_type: str = Form(...),
    invoice_no:   str = Form(""),
    invoice_date: str = Form(""),
    due_date:     str = Form(""),
    vendor_name:  str = Form(""),
    description:  str = Form(""),
    amount:       str = Form("0"),
    vat_rate:     str = Form("20"),
    document:     UploadFile = File(None),
):
    _require_finance(current_user)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Referans bulunamadı.")

    try:
        amt = float(amount or 0)
    except ValueError:
        amt = 0.0
    try:
        vat = float(vat_rate or 0)
    except ValueError:
        vat = 20.0

    vat_amt   = round(amt * vat / 100, 2)
    total_amt = round(amt + vat_amt, 2)

    inv = Invoice(
        id           = _uuid(),
        request_id   = req_id,
        invoice_type = invoice_type,
        invoice_no   = invoice_no.strip(),
        invoice_date = invoice_date or None,
        due_date     = due_date or None,
        vendor_name  = vendor_name.strip(),
        description  = description.strip(),
        amount       = amt,
        vat_rate     = vat,
        vat_amount   = vat_amt,
        total_amount = total_amt,
        status       = "active",
        created_by   = current_user.id,
        created_at   = _now(),
        updated_at   = _now(),
    )

    if document and document.filename:
        doc_path, doc_name = _save_document(document, inv.id)
        inv.document_path = doc_path
        inv.document_name = doc_name

    db.add(inv)
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}#tab-financial", status_code=303)


# ---------------------------------------------------------------------------
# GET /invoices/{id}/edit  — düzenleme formu
# ---------------------------------------------------------------------------

@router.get("/{invoice_id}/edit", response_class=HTMLResponse, name="invoices_edit_form")
async def invoices_edit_form(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)
    inv = _get_invoice_or_404(db, invoice_id)
    all_requests = db.query(ReqModel).order_by(ReqModel.created_at.desc()).all()
    return templates.TemplateResponse("invoices/form.html", {
        "request":       request,
        "current_user":  current_user,
        "page_title":    "Fatura Düzenle",
        "invoice":       inv,
        "selected_req":  inv.request,
        "all_requests":  all_requests,
        "invoice_types": INVOICE_TYPES,
        "edit_mode":     True,
    })


# ---------------------------------------------------------------------------
# POST /invoices/{id}/edit  — güncelle
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/edit", name="invoices_update")
async def invoices_update(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    invoice_type: str = Form(...),
    invoice_no:   str = Form(""),
    invoice_date: str = Form(""),
    due_date:     str = Form(""),
    vendor_name:  str = Form(""),
    description:  str = Form(""),
    amount:       str = Form("0"),
    vat_rate:     str = Form("20"),
    document:     UploadFile = File(None),
):
    _require_finance(current_user)
    inv = _get_invoice_or_404(db, invoice_id)

    try:
        amt = float(amount or 0)
    except ValueError:
        amt = 0.0
    try:
        vat = float(vat_rate or 0)
    except ValueError:
        vat = 20.0

    inv.invoice_type = invoice_type
    inv.invoice_no   = invoice_no.strip()
    inv.invoice_date = invoice_date or None
    inv.due_date     = due_date or None
    inv.vendor_name  = vendor_name.strip()
    inv.description  = description.strip()
    inv.amount       = amt
    inv.vat_rate     = vat
    inv.vat_amount   = round(amt * vat / 100, 2)
    inv.total_amount = round(amt + inv.vat_amount, 2)
    inv.updated_at   = _now()

    if document and document.filename:
        # Eski dosyayı sil
        if inv.document_path:
            old_path = os.path.join(os.path.dirname(__file__), "..", "static", inv.document_path)
            if os.path.exists(old_path):
                os.remove(old_path)
        doc_path, doc_name = _save_document(document, inv.id)
        inv.document_path = doc_path
        inv.document_name = doc_name

    db.commit()
    return RedirectResponse(url=f"/requests/{inv.request_id}#tab-financial", status_code=303)


# ---------------------------------------------------------------------------
# POST /invoices/{id}/delete  — iptal (soft delete)
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/delete", name="invoices_delete")
async def invoices_delete(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)
    inv = _get_invoice_or_404(db, invoice_id)
    req_id = inv.request_id
    inv.status     = "cancelled"
    inv.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}#tab-financial", status_code=303)


# ---------------------------------------------------------------------------
# GET /invoices/{id}/document  — belge dosyasını serve et
# ---------------------------------------------------------------------------

@router.get("/{invoice_id}/document", name="invoices_document")
async def invoices_document(
    invoice_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = _get_invoice_or_404(db, invoice_id)
    if not inv.document_path:
        raise HTTPException(status_code=404, detail="Belge bulunamadı.")
    file_path = os.path.join(os.path.dirname(__file__), "..", "static", inv.document_path)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Belge dosyası bulunamadı.")
    return FileResponse(
        path=file_path,
        filename=inv.document_name or os.path.basename(file_path),
        media_type="application/octet-stream",
    )
