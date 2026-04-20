"""
E-dem — Fatura Yönetimi
Erişim: admin, muhasebe_muduru, muhasebe
"""
import json
import os
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Budget, Invoice, INVOICE_TYPES, INVOICE_TYPE_LABELS, BELGESIZ_TYPES, Request as ReqModel, UndocumentedEntry, FinancialVendor, User, _uuid, _now
from routers.library import log_activity
from templates_config import templates

router = APIRouter(prefix="/invoices", tags=["invoices"])

FINANCE_ROLES        = {"admin", "muhasebe_muduru", "muhasebe"}
INVOICE_REQUEST_ROLES = {"admin", "mudur", "yonetici", "muhasebe_muduru", "muhasebe"}  # fatura talebi
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads", "invoices")
ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _require_finance(current_user: User):
    if current_user.role not in FINANCE_ROLES:
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")


def _is_gm(user: User) -> bool:
    """Admin rolü VEYA 'Genel Müdür' unvanına sahip kullanıcılar GM yetkisi taşır."""
    if user.role == "admin":
        return True
    if user.org_title and user.org_title.name == "Genel Müdür":
        return True
    return False


def _require_approval_permission(current_user: User, inv):
    """
    Onay/red için yetki:
    - pending        → mudur veya GM onaylayabilir
    - mudur_approved → sadece GM (admin veya Genel Müdür unvanlı) onaylayabilir
    """
    if _is_gm(current_user):
        return  # GM her adımda onaylayabilir
    if current_user.role == "mudur" and getattr(inv, "status", "") == "pending":
        return  # Müdür sadece pending'i onaylayabilir
    raise HTTPException(status_code=403, detail="Bu faturayı onaylamak/reddetmek için yetkiniz yok.")


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
# GET /invoices  — Genel Fatura Listesi
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="invoices_list")
async def invoices_list(
    request: Request,
    status_filter: str = "all",
    type_filter: str = "all",
    q: str = "",            # serbest metin: fatura no, tedarikçi, referans no
    date_from: str = "",    # YYYY-MM-DD
    date_to: str = "",      # YYYY-MM-DD
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Finans rolleri + PM (kendi referanslarının faturalarını görebilir)
    if current_user.role not in {"admin", "muhasebe_muduru", "muhasebe", "mudur", "yonetici", "asistan", "e_dem"}:
        raise HTTPException(status_code=403)

    query = db.query(Invoice).join(Invoice.request)

    # Birim müdürü: sadece takımının referanslarının faturaları
    if current_user.role == "mudur" and current_user.team_id:
        from models import Request as ReqModel
        query = query.filter(ReqModel.team_id == current_user.team_id)
    # PM sadece kendi referanslarının faturalarını görür
    elif current_user.role in ("yonetici", "asistan"):
        from models import Request as ReqModel
        query = query.filter(ReqModel.created_by == current_user.id)

    if status_filter != "all":
        query = query.filter(Invoice.status == status_filter)
    if type_filter != "all":
        query = query.filter(Invoice.invoice_type == type_filter)
    if q.strip():
        from models import Request as ReqModel
        term = f"%{q.strip()}%"
        query = query.filter(
            Invoice.invoice_no.ilike(term) |
            Invoice.vendor_name.ilike(term) |
            ReqModel.request_no.ilike(term) |
            ReqModel.event_name.ilike(term)
        )
    if date_from:
        query = query.filter(Invoice.invoice_date >= date_from)
    if date_to:
        query = query.filter(Invoice.invoice_date <= date_to)

    invoices = query.order_by(Invoice.created_at.desc()).all()

    _count_base = db.query(Invoice).join(Invoice.request)
    if current_user.role in ("yonetici", "asistan"):
        from models import Request as ReqModel
        _count_base = _count_base.filter(ReqModel.created_by == current_user.id)
    elif current_user.role == "mudur" and current_user.team_id:
        from models import Request as ReqModel
        _count_base = _count_base.filter(ReqModel.team_id == current_user.team_id)

    pending_count        = _count_base.filter(Invoice.status == "pending").count()
    mudur_approved_count = _count_base.filter(Invoice.status == "mudur_approved").count()

    can_cut           = current_user.role in ("admin", "muhasebe_muduru", "muhasebe")
    can_approve       = _is_gm(current_user) or current_user.role == "mudur"
    can_mudur_approve = _is_gm(current_user) or current_user.role == "mudur"
    can_gm_approve    = _is_gm(current_user)   # mudur_approved → gm_approved

    return templates.TemplateResponse("invoices/list.html", {
        "request":              request,
        "current_user":         current_user,
        "page_title":           "Faturalar",
        "invoices":             invoices,
        "status_filter":        status_filter,
        "type_filter":          type_filter,
        "q":                    q,
        "date_from":            date_from,
        "date_to":              date_to,
        "pending_count":        pending_count,
        "mudur_approved_count": mudur_approved_count,
        "invoice_types":        INVOICE_TYPES,
        "INVOICE_TYPE_LABELS":  {t["value"]: t["label"] for t in INVOICE_TYPES},
        "can_cut":              can_cut,
        "can_approve":          can_approve,
        "can_mudur_approve":    can_mudur_approve,
        "can_gm_approve":       can_gm_approve,
    })


# ---------------------------------------------------------------------------
# GET /invoices/new
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="invoices_new_form")
async def invoices_new_form(
    request: Request,
    request_id: str = "",
    statement_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # statement_id ile geliyorsa PM/yonetici de fatura talebi oluşturabilir
    if statement_id:
        if current_user.role not in INVOICE_REQUEST_ROLES:
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")
    else:
        _require_finance(current_user)
    req = None
    if request_id:
        req = db.query(ReqModel).filter(ReqModel.id == request_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Referans bulunamadı.")
    _req_q = db.query(ReqModel).filter(
        ReqModel.status.notin_(["cancelled", "closing", "closed"])
    )
    if current_user.role == "mudur" and current_user.team_id:
        _req_q = _req_q.filter(ReqModel.team_id == current_user.team_id)
    elif current_user.role in ("yonetici", "asistan"):
        _req_q = _req_q.filter(ReqModel.created_by == current_user.id)
    all_requests = _req_q.order_by(ReqModel.created_at.desc()).all()
    undoc_entries = req.undocumented_entries if req else []

    # Hesap dökümünden ön doldurma
    statement_prefill = None
    if statement_id:
        stmt = db.query(Budget).filter(Budget.id == statement_id, Budget.budget_type == "statement").first()
        if stmt:
            from collections import defaultdict
            ACCOM_SECTIONS = {"accommodation"}

            # Detaylı satırlar (tüm kalemler ayrı)
            invoice_lines = []
            # Gruplu satırlar için toplama
            accom_groups = defaultdict(float)   # vat_rate(int) -> total_amount (TRY)
            other_groups = defaultdict(float)   # vat_rate(int) -> total_amount (TRY)

            for row in stmt.rows:
                if row.get("is_service_fee"):
                    sale = float(row.get("sale_price", 0))
                    cur  = row.get("currency", "TRY") or "TRY"
                    sale_try = stmt.amount_to_try(sale, cur)
                    vat  = int(float(row.get("vat_rate", 20)))
                    if sale_try > 0:
                        invoice_lines.append({
                            "description": row.get("service_name", "Hizmet Bedeli"),
                            "amount":      round(sale_try, 2),
                            "vat_rate":    vat,
                            "vat_amount":  round(sale_try * vat / 100, 2),
                        })
                        other_groups[vat] += sale_try
                else:
                    sale   = float(row.get("sale_price", 0))
                    qty    = float(row.get("qty", 1))
                    nights = float(row.get("nights", 1))
                    cur    = row.get("currency", "TRY") or "TRY"
                    total_try = stmt.amount_to_try(sale * qty * nights, cur)
                    vat    = int(float(row.get("vat_rate", 20)))
                    if total_try > 0:
                        invoice_lines.append({
                            "description": row.get("service_name", row.get("description", "")),
                            "amount":      round(total_try, 2),
                            "vat_rate":    vat,
                            "vat_amount":  round(total_try * vat / 100, 2),
                        })
                        section = row.get("section", "")
                        if section in ACCOM_SECTIONS:
                            accom_groups[vat] += total_try
                        else:
                            other_groups[vat] += total_try

            # KDV gruplu satırlar oluştur
            grouped_lines = []
            for vat, amount in sorted(accom_groups.items()):
                amount = round(amount, 2)
                grouped_lines.append({
                    "description": "Konaklama Bedeli",
                    "amount":      amount,
                    "vat_rate":    vat,
                    "vat_amount":  round(amount * vat / 100, 2),
                })
            for vat, amount in sorted(other_groups.items()):
                amount = round(amount, 2)
                grouped_lines.append({
                    "description": f"Organizasyon Hizmet Bedeli (%{vat} KDV)",
                    "amount":      amount,
                    "vat_rate":    vat,
                    "vat_amount":  round(amount * vat / 100, 2),
                })

            customer_name = ""
            if req and req.customer_id:
                from models import Customer
                cust = db.query(Customer).filter(Customer.id == req.customer_id).first()
                if cust:
                    customer_name = cust.name
            if not customer_name and req:
                customer_name = req.client_name or ""

            statement_prefill = {
                "vendor_name":       customer_name,
                "invoice_type":      "kesilen",
                "description":       f"Hesap Dökümü — {stmt.venue_name} / {req.request_no if req else ''}",
                "lines_json":        json.dumps(invoice_lines, ensure_ascii=False),
                "grouped_lines_json": json.dumps(grouped_lines, ensure_ascii=False),
            }

    page_title = "Fatura Talebi Oluştur" if statement_prefill else "Yeni Fatura"

    return templates.TemplateResponse("invoices/form.html", {
        "request":           request,
        "current_user":      current_user,
        "page_title":        page_title,
        "invoice":           None,
        "selected_req":      req,
        "all_requests":      all_requests,
        "undoc_entries":     undoc_entries,
        "invoice_types":     INVOICE_TYPES,
        "edit_mode":         False,
        "statement_prefill": statement_prefill,
        "from_statement":    statement_id,
    })


# ---------------------------------------------------------------------------
# POST /invoices/new
# ---------------------------------------------------------------------------

@router.post("/new", name="invoices_create")
async def invoices_create(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    req_id:              str = Form(""),
    invoice_type:        str = Form(...),
    invoice_no:          str = Form(""),
    invoice_date:        str = Form(""),
    due_date:            str = Form(""),
    vendor_id:           str = Form(""),
    vendor_name:         str = Form(""),
    define_vendor:       str = Form("no"),   # "yes" → yeni FinancialVendor oluştur
    vendor_payment_term: str = Form("60"),   # gün
    description:         str = Form(""),
    lines_json:          str = Form("[]"),
    belgesiz_amount:     str = Form(""),
    belgesiz_description:str = Form(""),
    belgesiz_date:       str = Form(""),
    from_statement:      str = Form(""),   # statement ID — PM'den gelenler
    document:            UploadFile = File(None),
):
    # Statement üzerinden gelen fatura talepleri PM/yonetici'ye de açık
    if from_statement:
        if current_user.role not in INVOICE_REQUEST_ROLES:
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")
    else:
        _require_finance(current_user)
    req = None
    if req_id:
        req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Referans bulunamadı.")

    # ── Belgesiz Gelir / Gider → UndocumentedEntry kaydet ──
    if invoice_type in BELGESIZ_TYPES:
        if not req:
            raise HTTPException(status_code=400, detail="Belgesiz giriş için referans seçilmesi zorunludur.")
        entry_type = "gelir" if invoice_type == "belgesiz_gelir" else "gider"
        entry = UndocumentedEntry(
            id          = _uuid(),
            request_id  = req_id,
            entry_type  = entry_type,
            description = belgesiz_description.strip(),
            amount      = float(belgesiz_amount or 0),
            entry_date  = belgesiz_date or "",
            created_by  = current_user.id,
            created_at  = _now(),
        )
        db.add(entry)
        db.commit()
        return RedirectResponse(url=f"/requests/{req_id}#tab-financial", status_code=303)

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
        request_id   = req_id or None,
        invoice_type = invoice_type,
        invoice_no   = invoice_no.strip(),
        invoice_date = invoice_date or None,
        due_date     = due_date or None,
        vendor_id    = vendor_id.strip() or None,
        vendor_name  = vendor_name.strip(),
        description  = description.strip(),
        lines_json   = json.dumps(lines, ensure_ascii=False),
        amount       = excl,
        vat_rate     = first_vat,
        vat_amount   = vat_total,
        total_amount = incl,
        status       = "pending",
        created_by   = current_user.id,
        created_at   = _now(),
        updated_at   = _now(),
    )

    if document and document.filename:
        doc_path, doc_name = _save_document(document, inv.id)
        inv.document_path = doc_path
        inv.document_name = doc_name

    db.add(inv)
    db.flush()

    # ── Tanımlı tedarikçi oluştur / bağla ──────────────────────────────────
    _resolved_vendor_id = vendor_id.strip() or None
    if define_vendor == "yes" and not _resolved_vendor_id and vendor_name.strip():
        # Aynı isimde zaten var mı kontrol et (case-insensitive)
        existing_fv = db.query(FinancialVendor).filter(
            FinancialVendor.name.ilike(vendor_name.strip())
        ).first()
        if existing_fv:
            _resolved_vendor_id = existing_fv.id
        else:
            _pt = max(1, int(vendor_payment_term or 60))
            new_fv = FinancialVendor(
                id           = _uuid(),
                name         = vendor_name.strip(),
                payment_term = _pt,
                is_active    = True,
                created_by   = current_user.id,
                created_at   = _now(),
                updated_at   = _now(),
            )
            db.add(new_fv)
            db.flush()
            _resolved_vendor_id = new_fv.id

        # Bu faturayı ilişkilendir
        inv.vendor_id = _resolved_vendor_id

        # Aynı vendor_name sahip geçmiş faturaları da backfill et
        if _resolved_vendor_id:
            db.query(Invoice).filter(
                Invoice.vendor_name.ilike(vendor_name.strip()),
                Invoice.vendor_id == None,
                Invoice.id != inv.id,
            ).update({"vendor_id": _resolved_vendor_id}, synchronize_session=False)

    # Kütüphane: fatura girişi logu
    from models import INVOICE_TYPE_LABELS as _ITL
    if req_id:
        log_activity(
            db, req_id, "invoice_created",
            f"Fatura eklendi — {_ITL.get(inv.invoice_type, inv.invoice_type)}: {inv.vendor_name or inv.invoice_no or '—'}",
            detail=f"Tutar: ₺{inv.amount:,.0f}",
            user_id=current_user.id,
        )
    db.commit()

    # Bildirim: ilgili taraflara fatura onay bildirimi gönder
    if req:
        from utils.notifications import create_notification
        from models import Team as _Team
        vendor = inv.vendor_name or inv.invoice_no or "—"

        # Takımın müdürüne bildirim (onay yetkisi olan kişi)
        _notified_ids = set()
        if req.team_id:
            _team = db.query(_Team).filter(_Team.id == req.team_id).first()
            _team_mudur = _team.mudur if _team else None
            if _team_mudur and _team_mudur.id != current_user.id:
                create_notification(
                    db,
                    user_id    = _team_mudur.id,
                    notif_type = "invoice_pending",
                    title      = f"Fatura onayı bekleniyor — {vendor}",
                    message    = f"{req.request_no} referansına ait fatura onayınızı bekliyor.",
                    link       = f"/requests/{req_id}#tab-financial",
                    ref_id     = inv.id,
                )
                _notified_ids.add(_team_mudur.id)

        # Talebi oluşturan PM'e bildirim (müdür değilse + kendisi değilse)
        if req.created_by and req.created_by not in _notified_ids and req.created_by != current_user.id:
            create_notification(
                db,
                user_id    = req.created_by,
                notif_type = "invoice_pending",
                title      = f"Fatura eklendi — {vendor}",
                message    = f"{req.request_no} referansına fatura eklendi.",
                link       = f"/requests/{req_id}#tab-financial",
                ref_id     = inv.id,
            )
        db.commit()

    if req_id:
        return RedirectResponse(url=f"/requests/{req_id}#tab-financial", status_code=303)
    return RedirectResponse(url="/invoices/unlinked", status_code=303)


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
    all_requests = db.query(ReqModel).filter(
        ReqModel.status.notin_(["cancelled", "closing", "closed"])
    ).order_by(ReqModel.created_at.desc()).all()
    undoc_entries = inv.request.undocumented_entries if inv.request else []
    return templates.TemplateResponse("invoices/form.html", {
        "request":       request,
        "current_user":  current_user,
        "page_title":    "Fatura Düzenle",
        "invoice":       inv,
        "selected_req":  inv.request,
        "all_requests":  all_requests,
        "undoc_entries": undoc_entries,
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
    vendor_id:    str = Form(""),
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
    inv.vendor_id    = vendor_id.strip() or None
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
    if inv.request_id:
        return RedirectResponse(url=f"/requests/{inv.request_id}#tab-financial", status_code=303)
    return RedirectResponse(url="/invoices/unlinked", status_code=303)


# ---------------------------------------------------------------------------
# POST /invoices/parse-pdf  — PDF'den otomatik fatura doldurma (AI'sız)
# ---------------------------------------------------------------------------

@router.post("/parse-pdf", name="invoices_parse_pdf")
async def invoices_parse_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    _require_finance(current_user)

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        return JSONResponse({"error": "Dosya 10 MB'ı aşıyor."}, status_code=400)

    try:
        from agents.invoice_parser import parse_invoice, _debug_extract
        debug = _debug_extract(file_bytes)
        print("[PARSE-PDF DEBUG] Tables:", len(debug.get("tables", [])), flush=True)
        for i, t in enumerate(debug.get("tables", [])):
            print(f"  Table {i}: {len(t)} rows, header={t[0] if t else 'empty'}", flush=True)
            for row in t[1:4]:
                print(f"    row: {row}", flush=True)
        data = parse_invoice(file_bytes, file.filename or "invoice.pdf")
        return JSONResponse({"ok": True, "data": data})
    except Exception as e:
        import traceback
        print(f"[PARSE-PDF] Hata: {e}\n{traceback.format_exc()}", flush=True)
        return JSONResponse({"error": "PDF okunamadı. Dosyayı kontrol edin."}, status_code=400)


# ---------------------------------------------------------------------------
# POST /invoices/{id}/approve  — referans sahibi (PM) veya admin onaylar
# ---------------------------------------------------------------------------
# POST /invoices/{id}/cut  — Muhasebe faturayı keser (detayları doldurur + onaylar)
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/cut", name="invoices_cut")
async def invoices_cut(
    invoice_id:   str,
    request:      Request,
    current_user: User = Depends(get_current_user),
    db:           Session = Depends(get_db),
    invoice_no:   str = Form(""),
    invoice_date: str = Form(""),
    due_date:     str = Form(""),
    document:     UploadFile = File(None),
):
    """Muhasebe onaylı faturaya detay ekler (fatura no, tarih, belge). Durum değişmez."""
    _require_finance(current_user)
    inv = _get_invoice_or_404(db, invoice_id)
    if inv.status not in ("approved", "gm_approved"):
        raise HTTPException(status_code=400, detail="Sadece onaylı faturalara detay eklenebilir.")

    if invoice_no.strip():
        inv.invoice_no = invoice_no.strip()
    if invoice_date:
        inv.invoice_date = invoice_date
    if due_date:
        inv.due_date = due_date

    if document and document.filename:
        doc_path, doc_name = _save_document(document, inv.id)
        inv.document_path = doc_path
        inv.document_name = doc_name

    # Eski gm_approved kayıtlar için durum approved'a güncellenir; zaten approved olanlar değişmez
    if inv.status == "gm_approved":
        inv.status = "approved"
    inv.updated_at  = _now()
    db.commit()
    return RedirectResponse(url="/invoices?status_filter=gm_approved", status_code=303)


# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/approve", name="invoices_approve")
async def invoices_approve(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = _get_invoice_or_404(db, invoice_id)
    _require_approval_permission(current_user, inv)

    if inv.status == "pending":
        if _is_gm(current_user):
            # GM direkt onaylar → approved (muhasebe adımı yok)
            inv.status = "approved"
        elif current_user.role == "mudur":
            # Müdür onayı: limit kontrolü
            from models import Settings
            settings = db.query(Settings).filter(Settings.id == 1).first()
            limit = getattr(settings, "invoice_mudur_limit", None) if settings else None
            if limit is not None and (inv.total_amount or 0) <= limit:
                # Tutar limit dahilinde → GM onayı gerekmez, doğrudan onaylandı
                inv.status = "approved"
            else:
                # Limit yok veya tutar limiti aşıyor → GM onayı gerekli
                inv.status = "mudur_approved"
        else:
            raise HTTPException(status_code=403, detail="Bu aşamada onay yetkiniz yok.")
    elif inv.status == "mudur_approved":
        if _is_gm(current_user):
            # GM onayı: mudur_approved → approved (doğrudan)
            inv.status = "approved"
        else:
            raise HTTPException(status_code=403, detail="Bu aşamada sadece GM onaylayabilir.")
    elif inv.status == "gm_approved":
        # Eski kayıtlar için geriye dönük uyumluluk
        if _is_gm(current_user) or current_user.role in ("muhasebe_muduru", "muhasebe"):
            inv.status = "approved"
        else:
            raise HTTPException(status_code=403, detail="Bu aşamada yetkiniz yok.")
    else:
        raise HTTPException(status_code=400, detail="Bu fatura onay için uygun durumda değil.")

    inv.approved_by    = current_user.id
    inv.approved_at    = _now()
    inv.rejection_note = ""
    inv.updated_at     = _now()
    db.commit()

    if inv.status == "mudur_approved":
        return RedirectResponse(url="/invoices?status_filter=pending", status_code=303)
    return RedirectResponse(url="/invoices?status_filter=approved", status_code=303)


# ---------------------------------------------------------------------------
# POST /invoices/{id}/reject  — referans sahibi (PM) veya admin reddeder
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/reject", name="invoices_reject")
async def invoices_reject(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    rejection_note: str = Form(""),
):
    inv = _get_invoice_or_404(db, invoice_id)
    _require_approval_permission(current_user, inv)

    if inv.status not in ("pending", "mudur_approved", "approved"):
        raise HTTPException(status_code=400, detail="Bu fatura iptal edilmiş.")

    inv.status         = "rejected"
    inv.rejection_note = rejection_note.strip()[:300]
    inv.approved_by    = None
    inv.approved_at    = None
    inv.updated_at     = _now()
    db.commit()
    if inv.request_id:
        return RedirectResponse(url=f"/requests/{inv.request_id}#tab-financial", status_code=303)
    return RedirectResponse(url="/invoices/unlinked", status_code=303)


# ---------------------------------------------------------------------------
# POST /invoices/{id}/reassign  — sadece admin, referansı değiştirir
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/reassign", name="invoices_reassign")
async def invoices_reassign(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    new_request_id: str = Form(...),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Sadece admin referans değiştirebilir.")

    inv = _get_invoice_or_404(db, invoice_id)
    old_req_id = inv.request_id

    new_req = db.query(ReqModel).filter(ReqModel.id == new_request_id).first()
    if not new_req:
        raise HTTPException(status_code=404, detail="Hedef referans bulunamadı.")

    inv.request_id = new_request_id
    inv.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{old_req_id}#tab-financial", status_code=303)


# ---------------------------------------------------------------------------
# GET /invoices/unlinked  — Referans bekleyen faturalar (herkese görünür)
# ---------------------------------------------------------------------------

@router.get("/unlinked", response_class=HTMLResponse, name="invoices_unlinked")
async def invoices_unlinked(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invoices = (
        db.query(Invoice)
        .filter(Invoice.request_id == None, Invoice.status != "cancelled")
        .order_by(Invoice.created_at.desc())
        .all()
    )
    req_q = db.query(ReqModel).filter(
        ReqModel.status.notin_(["cancelled", "closing", "closed"])
    )
    # mudur: kendi takımının tüm referansları
    if current_user.role == "mudur" and current_user.team_id:
        req_q = req_q.filter(ReqModel.team_id == current_user.team_id)
    # yonetici/asistan: sadece kendi referansları
    elif current_user.role in ("yonetici", "asistan"):
        req_q = req_q.filter(ReqModel.created_by == current_user.id)
    # admin/muhasebe: filtre yok
    all_requests = req_q.order_by(ReqModel.created_at.desc()).all()
    return templates.TemplateResponse("invoices/unlinked.html", {
        "request":      request,
        "current_user": current_user,
        "page_title":   "Referans Bekleyen Faturalar",
        "invoices":     invoices,
        "all_requests": all_requests,
        "invoice_types": INVOICE_TYPES,
    })


# ---------------------------------------------------------------------------
# POST /invoices/{id}/assign-request  — Faturaya referans ata
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/assign-request", name="invoices_assign_request")
async def invoices_assign_request(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    new_request_id: str = Form(...),
):
    inv = _get_invoice_or_404(db, invoice_id)
    if inv.request_id:
        raise HTTPException(status_code=400, detail="Bu faturanın zaten bir referansı var.")

    new_req = db.query(ReqModel).filter(ReqModel.id == new_request_id).first()
    if not new_req:
        raise HTTPException(status_code=404, detail="Hedef referans bulunamadı.")
    if current_user.role == "mudur" and current_user.team_id:
        if new_req.team_id != current_user.team_id:
            raise HTTPException(status_code=403, detail="Bu referans takımınıza ait değil.")
    elif current_user.role in ("yonetici", "asistan"):
        if new_req.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="Bu referansa atama yetkiniz yok.")

    inv.request_id = new_request_id
    inv.updated_at = _now()

    from models import INVOICE_TYPE_LABELS as _ITL
    log_activity(
        db, new_request_id, "invoice_assigned",
        f"Fatura referansa atandı — {_ITL.get(inv.invoice_type, inv.invoice_type)}: {inv.vendor_name or inv.invoice_no or '—'}",
        detail=f"Tutar: ₺{inv.amount:,.0f}",
        user_id=current_user.id,
    )
    db.commit()
    return RedirectResponse(url=f"/requests/{new_request_id}#tab-financial", status_code=303)


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
    if req_id:
        return RedirectResponse(url=f"/requests/{req_id}#tab-financial", status_code=303)
    return RedirectResponse(url="/invoices/unlinked", status_code=303)


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
