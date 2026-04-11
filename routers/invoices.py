"""
E-dem — Fatura Yönetimi
Erişim: admin, muhasebe_muduru, muhasebe
"""
import base64
import json
import os
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
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
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="Desteklenmeyen dosya türü. PDF veya resim yükleyin.")
    dest_filename = f"{invoice_id}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, dest_filename)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    if os.path.getsize(dest_path) > MAX_FILE_SIZE:
        os.remove(dest_path)
        raise HTTPException(status_code=400, detail="Dosya boyutu 10 MB'ı aşamaz.")
    return f"uploads/invoices/{dest_filename}", file.filename or dest_filename


def _compute_totals(lines: list) -> tuple[float, float, float]:
    """lines'dan (amount_excl, vat_amount, total_incl) hesapla."""
    total_excl = sum(float(l.get("amount", 0) or 0) for l in lines)
    total_vat  = sum(float(l.get("vat_amount", 0) or 0) for l in lines)
    return round(total_excl, 2), round(total_vat, 2), round(total_excl + total_vat, 2)


# ---------------------------------------------------------------------------
# GET /invoices/new
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
# POST /invoices/new
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
    lines_json:   str = Form("[]"),
    document:     UploadFile = File(None),
):
    _require_finance(current_user)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Referans bulunamadı.")

    try:
        lines = json.loads(lines_json or "[]")
    except Exception:
        lines = []

    # Her satırın vat_amount'unu hesapla
    for ln in lines:
        amt = float(ln.get("amount", 0) or 0)
        vat = float(ln.get("vat_rate", 0) or 0)
        ln["vat_amount"] = round(amt * vat / 100, 2)

    excl, vat_total, incl = _compute_totals(lines)
    # geriye uyumluluk için vat_rate: ilk satırın oranı (veya 0)
    first_vat = float(lines[0].get("vat_rate", 0)) if lines else 0.0

    inv = Invoice(
        id           = _uuid(),
        request_id   = req_id,
        invoice_type = invoice_type,
        invoice_no   = invoice_no.strip(),
        invoice_date = invoice_date or None,
        due_date     = due_date or None,
        vendor_name  = vendor_name.strip(),
        description  = description.strip(),
        lines_json   = json.dumps(lines, ensure_ascii=False),
        amount       = excl,
        vat_rate     = first_vat,
        vat_amount   = vat_total,
        total_amount = incl,
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
# GET /invoices/{id}/edit
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
# POST /invoices/{id}/edit
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
    lines_json:   str = Form("[]"),
    document:     UploadFile = File(None),
):
    _require_finance(current_user)
    inv = _get_invoice_or_404(db, invoice_id)

    try:
        lines = json.loads(lines_json or "[]")
    except Exception:
        lines = []

    for ln in lines:
        amt = float(ln.get("amount", 0) or 0)
        vat = float(ln.get("vat_rate", 0) or 0)
        ln["vat_amount"] = round(amt * vat / 100, 2)

    excl, vat_total, incl = _compute_totals(lines)
    first_vat = float(lines[0].get("vat_rate", 0)) if lines else 0.0

    inv.invoice_type = invoice_type
    inv.invoice_no   = invoice_no.strip()
    inv.invoice_date = invoice_date or None
    inv.due_date     = due_date or None
    inv.vendor_name  = vendor_name.strip()
    inv.description  = description.strip()
    inv.lines_json   = json.dumps(lines, ensure_ascii=False)
    inv.amount       = excl
    inv.vat_rate     = first_vat
    inv.vat_amount   = vat_total
    inv.total_amount = incl
    inv.updated_at   = _now()

    if document and document.filename:
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
# POST /invoices/parse-pdf  — Claude API ile PDF'den otomatik doldur
# ---------------------------------------------------------------------------

@router.post("/parse-pdf", name="invoices_parse_pdf")
async def invoices_parse_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    _require_finance(current_user)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY sunucuda tanımlı değil. Railway ortam değişkenlerine ekleyin."}, status_code=500)

    import anthropic as _anthropic

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        return JSONResponse({"error": "Dosya 10 MB'ı aşıyor."}, status_code=400)

    ext = os.path.splitext(file.filename or "")[1].lower()
    b64 = base64.standard_b64encode(file_bytes).decode()

    # PDF için document block, resimler için image block
    if ext == ".pdf":
        media_type = "application/pdf"
        content_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }
    else:
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        media_type = mime_map.get(ext, "image/jpeg")
        content_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }

    prompt = """Bu fatura belgesinden bilgileri çıkar ve SADECE aşağıdaki JSON formatında döndür. Başka hiçbir metin yazma.

{
  "invoice_no": "fatura/fiş numarası",
  "invoice_date": "YYYY-MM-DD (kesim tarihi)",
  "due_date": "YYYY-MM-DD (son ödeme/vade tarihi, yoksa boş string)",
  "vendor_name": "faturayı kesen firma/kişi adı",
  "description": "fatura üstündeki genel açıklama veya sipariş notu (varsa, yoksa boş string)",
  "lines": [
    {
      "description": "kalem adı/açıklaması",
      "amount": 1000.00,
      "vat_rate": 10
    }
  ]
}

ZORUNLU KURALLAR:
1. amount = KDV HARİÇ net tutar (matrah). KDV dahil toplam değil.
   - Faturada "Matrah" veya "KDV Hariç Tutar" sütunu varsa onu al.
   - Yoksa: KDV dahil tutarı (1 + kdv_oranı) ile böl. Örn: KDV %10 ise amount = toplam / 1.10
2. vat_rate = tam sayı KDV yüzdesi (örn: 10, 20). Sadece şu değerler geçerli: 0, 1, 8, 10, 18, 20.
   - Faturadaki KDV oranı bu listede yoksa en yakın geçerli orana yuvarla.
   - Örn: %13 → 10, %25 → 20
3. Her farklı KDV oranı için ayrı satır oluştur. Toplam/ara toplam satırlarını lines'a EKLEME.
4. Tüm sayısal değerlerde ondalık ayırıcı olarak nokta kullan (virgül değil).
5. Tarihler mutlaka YYYY-MM-DD formatında olmalı.
6. Bilinmeyen alanlar: boş string ("") veya 0."""

    try:
        client = _anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [content_block, {"type": "text", "text": prompt}],
            }],
        )
        text = response.content[0].text.strip()
        # JSON bloğu varsa çıkar
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        data = json.loads(text)
        return JSONResponse({"ok": True, "data": data})
    except json.JSONDecodeError as e:
        return JSONResponse({"error": f"AI yanıtı parse edilemedi: {e}"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"AI hatası: {e}"}, status_code=500)


# ---------------------------------------------------------------------------
# POST /invoices/{id}/delete
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
# GET /invoices/{id}/document
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
