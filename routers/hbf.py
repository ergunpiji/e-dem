"""
HBF — Harcama Bildirim Formu yönetimi
"""

import json
import os
import shutil
import uuid
from datetime import date as _date, datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

UPLOAD_DIR = "static/uploads/hbf"
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".xlsx", ".xls", ".docx", ".doc"}

from auth import get_current_user
from database import get_db, generate_hbf_no
from models import (
    HBF, HBF_STATUS_LABELS, Employee, Reference,
    User, CashBook, BankAccount, GeneralExpense,
    GeneralExpenseCategory, CashEntry, BankMovement,
    PAYMENT_METHODS,
)
from templates_config import templates

router = APIRouter(prefix="/hbf", tags=["hbf"])


def _parse_items(items_json: str) -> tuple[list, float]:
    """
    items_json iki formatta gelebilir:
      - Yeni (gruplu): [{ref_id, ref_no, ref_title, items:[...]}]
      - Eski (düz):    [{description, amount, ...}]
    Her zaman gruplu listeyi döndürür (detay/liste şablonu için tutarlılık).
    """
    try:
        data = json.loads(items_json or "[]")
    except Exception:
        data = []
    if not data:
        return [], 0.0
    # Gruplu format tespiti: ilk elemanın "items" anahtarı varsa
    if isinstance(data[0], dict) and "items" in data[0]:
        sections = data
        total = sum(
            float(item.get("amount_with_vat", item.get("amount", 0)))
            for sec in sections
            for item in sec.get("items", [])
        )
        return sections, total
    # Eski düz format → tek anonim section olarak sar
    total = sum(float(i.get("amount_with_vat", i.get("amount", 0))) for i in data)
    return [{"ref_id": None, "ref_no": "", "ref_title": "", "items": data}], total


def _parse_refs(refs_json: str) -> tuple[list, int | None]:
    """refs_json → (list, first_ref_id)"""
    try:
        refs = json.loads(refs_json or "[]")
    except Exception:
        refs = []
    first_id = refs[0]["id"] if refs else None
    return refs, first_id


def _hbf_expense_category(db) -> int:
    cat = db.query(GeneralExpenseCategory).filter_by(name="HBF Harcaması").first()
    if not cat:
        parent = db.query(GeneralExpenseCategory).filter_by(name="Diğer", parent_id=None).first()
        cat = GeneralExpenseCategory(
            name="HBF Harcaması",
            parent_id=parent.id if parent else None,
            sort_order=99,
        )
        db.add(cat)
        db.flush()
    return cat.id


# ---------------------------------------------------------------------------
# Geçici yükleme yardımcısı
# ---------------------------------------------------------------------------

def _process_row_attachments(
    hbf_id: int,
    form_token: str,
    row_atts_input: dict,
    existing_atts: list,
) -> list:
    """
    row_atts_input: {row_id: {filename, original}}  — form'dan gelen
    existing_atts : mevcut attachments_json listesi
    Döner: yeni attachments listesi
    """
    hbf_dir = os.path.join(UPLOAD_DIR, str(hbf_id))
    os.makedirs(hbf_dir, exist_ok=True)

    existing_map = {a["row_id"]: a for a in existing_atts if a.get("row_id")}
    global_atts  = [a for a in existing_atts if not a.get("row_id")]
    new_atts     = list(global_atts)

    for row_id, att_info in row_atts_input.items():
        tmp_path = os.path.join(UPLOAD_DIR, "tmp", form_token, att_info["filename"])
        if os.path.exists(tmp_path):
            _, ext = os.path.splitext(att_info["filename"])
            new_fn = f"{uuid.uuid4().hex}{ext}"
            shutil.move(tmp_path, os.path.join(hbf_dir, new_fn))
            # Önceki dosyayı sil (satır değiştirildi)
            if row_id in existing_map:
                old_path = os.path.join(hbf_dir, existing_map[row_id]["filename"])
                if os.path.exists(old_path):
                    os.remove(old_path)
            new_atts.append({
                "row_id": row_id,
                "filename": new_fn,
                "original": att_info["original"],
                "uploaded_at": _date.today().isoformat(),
            })
        elif row_id in existing_map:
            new_atts.append(existing_map[row_id])

    # Tmp dizinini temizle
    tmp_dir = os.path.join(UPLOAD_DIR, "tmp", form_token)
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return new_atts


# ---------------------------------------------------------------------------
# Geçici dosya yükleme (form kaydedilmeden önce)
# ---------------------------------------------------------------------------

@router.post("/tmp-upload", name="hbf_tmp_upload")
async def hbf_tmp_upload(
    file: UploadFile = File(...),
    form_token: str = Form(...),
    row_id: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen dosya türü: {ext}")

    tmp_dir = os.path.join(UPLOAD_DIR, "tmp", form_token)
    os.makedirs(tmp_dir, exist_ok=True)

    # Satır başına tek dosya: row_id{ext} olarak sakla
    safe_name = f"{row_id}{ext}"
    dest = os.path.join(tmp_dir, safe_name)
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    return JSONResponse({"filename": safe_name, "original": file.filename, "row_id": row_id})


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="hbf_list")
async def hbf_list(
    request: Request,
    status_filter: str = "all",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(HBF)
    if not (current_user.is_admin or current_user.is_approver):
        q = q.filter(HBF.created_by == current_user.id)
    if status_filter != "all":
        q = q.filter(HBF.status == status_filter)
    forms = q.order_by(HBF.created_at.desc()).all()
    return templates.TemplateResponse(
        "hbf/list.html",
        {
            "request": request, "current_user": current_user,
            "forms": forms, "status_filter": status_filter,
            "status_labels": HBF_STATUS_LABELS,
            "page_title": "Harcama Bildirimleri",
        },
    )


# ---------------------------------------------------------------------------
# Yeni HBF
# ---------------------------------------------------------------------------

def _refs_for_template(db):
    refs = db.query(Reference).filter(Reference.status == "aktif").order_by(Reference.ref_no).all()
    return [{"id": r.id, "ref_no": r.ref_no, "title": r.title} for r in refs]


@router.get("/new", response_class=HTMLResponse, name="hbf_new_get")
async def hbf_new_get(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    employees = db.query(Employee).filter(Employee.active == True).order_by(Employee.name).all()  # noqa: E712
    return templates.TemplateResponse(
        "hbf/form.html",
        {
            "request": request, "current_user": current_user,
            "hbf": None, "employees": employees,
            "refs_data": json.dumps(_refs_for_template(db), ensure_ascii=False),
            "form_token": uuid.uuid4().hex,
            "existing_row_atts": "{}",
            "page_title": "Yeni Harcama Bildirimi",
        },
    )


@router.post("/new", name="hbf_new_post")
async def hbf_new_post(
    refs_json: str = Form("[]"),
    employee_id: int = Form(None),
    items_json: str = Form("[]"),
    notes: str = Form(""),
    action: str = Form("taslak"),
    form_token: str = Form(""),
    row_attachments_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = _parse_items(items_json)
    refs, first_ref_id = _parse_refs(refs_json)
    ref_nos = ", ".join(r["ref_no"] for r in refs) if refs else None
    hbf_status = "beklemede" if action == "gonder" else "taslak"
    hbf = HBF(
        hbf_no=generate_hbf_no(db),
        ref_id=first_ref_id,
        refs_json=refs_json if refs else None,
        employee_id=employee_id or None,
        title=ref_nos or "HBF",
        items_json=json.dumps(items, ensure_ascii=False),
        total_amount=total,
        status=hbf_status,
        notes=notes.strip() or None,
        created_by=current_user.id,
    )
    db.add(hbf)
    db.flush()

    try:
        row_atts = json.loads(row_attachments_json or "{}")
    except Exception:
        row_atts = {}
    if row_atts and form_token:
        new_atts = _process_row_attachments(hbf.id, form_token, row_atts, [])
        if new_atts:
            hbf.attachments_json = json.dumps(new_atts, ensure_ascii=False)

    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf.id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Detay
# ---------------------------------------------------------------------------

@router.get("/{hbf_id}", response_class=HTMLResponse, name="hbf_detail")
async def hbf_detail(
    hbf_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if not hbf:
        raise HTTPException(status_code=404)
    if not (current_user.is_admin or current_user.is_approver or hbf.created_by == current_user.id):
        raise HTTPException(status_code=403)

    items, _ = _parse_items(hbf.items_json)
    refs, _ = _parse_refs(hbf.refs_json)
    cash_books = db.query(CashBook).all()
    bank_accounts = db.query(BankAccount).all()

    kdv_haric = sum(
        float(item.get("amount_without_vat", item.get("amount", 0)))
        for sec in items for item in sec.get("items", [])
    )
    kdv_toplam = sum(
        float(item.get("vat_amount", 0))
        for sec in items for item in sec.get("items", [])
    )

    try:
        attachments = json.loads(hbf.attachments_json or "[]")
    except Exception:
        attachments = []
    row_attachments = {a["row_id"]: a for a in attachments if a.get("row_id")}
    global_attachments = [a for a in attachments if not a.get("row_id")]

    return templates.TemplateResponse(
        "hbf/detail.html",
        {
            "request": request, "current_user": current_user,
            "hbf": hbf, "items": items, "refs": refs,
            "kdv_haric": kdv_haric, "kdv_toplam": kdv_toplam,
            "status_labels": HBF_STATUS_LABELS,
            "cash_books": cash_books, "bank_accounts": bank_accounts,
            "payment_methods": PAYMENT_METHODS,
            "today": _date.today(),
            "row_attachments": row_attachments,
            "global_attachments": global_attachments,
            "page_title": hbf.hbf_no,
        },
    )


# ---------------------------------------------------------------------------
# Düzenle (sadece taslak)
# ---------------------------------------------------------------------------

@router.get("/{hbf_id}/edit", response_class=HTMLResponse, name="hbf_edit_get")
async def hbf_edit_get(
    hbf_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "taslak":
        raise HTTPException(status_code=404)
    if hbf.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403)
    employees = db.query(Employee).filter(Employee.active == True).order_by(Employee.name).all()  # noqa: E712
    try:
        existing_atts = json.loads(hbf.attachments_json or "[]")
    except Exception:
        existing_atts = []
    existing_row_atts = {
        a["row_id"]: {"filename": a["filename"], "original": a["original"]}
        for a in existing_atts if a.get("row_id")
    }
    return templates.TemplateResponse(
        "hbf/form.html",
        {
            "request": request, "current_user": current_user,
            "hbf": hbf, "employees": employees,
            "refs_data": json.dumps(_refs_for_template(db), ensure_ascii=False),
            "form_token": uuid.uuid4().hex,
            "existing_row_atts": json.dumps(existing_row_atts, ensure_ascii=False),
            "page_title": f"Düzenle — {hbf.hbf_no}",
        },
    )


@router.post("/{hbf_id}/edit", name="hbf_edit_post")
async def hbf_edit_post(
    hbf_id: int,
    refs_json: str = Form("[]"),
    employee_id: int = Form(None),
    items_json: str = Form("[]"),
    notes: str = Form(""),
    action: str = Form("taslak"),
    form_token: str = Form(""),
    row_attachments_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "taslak":
        raise HTTPException(status_code=404)
    items, total = _parse_items(items_json)
    refs, first_ref_id = _parse_refs(refs_json)
    ref_nos = ", ".join(r["ref_no"] for r in refs) if refs else None
    hbf.refs_json = refs_json if refs else None
    hbf.ref_id = first_ref_id
    hbf.title = ref_nos or hbf.title or "HBF"
    hbf.employee_id = employee_id or None
    hbf.items_json = json.dumps(items, ensure_ascii=False)
    hbf.total_amount = total
    hbf.notes = notes.strip() or None
    if action == "gonder":
        hbf.status = "beklemede"

    try:
        row_atts = json.loads(row_attachments_json or "{}")
    except Exception:
        row_atts = {}
    if form_token:
        try:
            existing_atts = json.loads(hbf.attachments_json or "[]")
        except Exception:
            existing_atts = []
        new_atts = _process_row_attachments(hbf_id, form_token, row_atts, existing_atts)
        hbf.attachments_json = json.dumps(new_atts, ensure_ascii=False) if new_atts else hbf.attachments_json

    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Gönder (taslak → beklemede)
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/submit", name="hbf_submit")
async def hbf_submit(
    hbf_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "taslak":
        raise HTTPException(status_code=404)
    hbf.status = "beklemede"
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Onayla / Reddet (is_approver veya admin)
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/approve", name="hbf_approve")
async def hbf_approve(
    hbf_id: int,
    approval_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not (current_user.is_admin or current_user.is_approver):
        raise HTTPException(status_code=403)
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "beklemede":
        raise HTTPException(status_code=404)
    hbf.status = "onaylandi"
    hbf.approved_by = current_user.id
    hbf.approved_at = datetime.utcnow()
    hbf.approval_note = approval_note.strip() or None
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{hbf_id}/reject", name="hbf_reject")
async def hbf_reject(
    hbf_id: int,
    approval_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not (current_user.is_admin or current_user.is_approver):
        raise HTTPException(status_code=403)
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "beklemede":
        raise HTTPException(status_code=404)
    hbf.status = "reddedildi"
    hbf.approved_by = current_user.id
    hbf.approved_at = datetime.utcnow()
    hbf.approval_note = approval_note.strip() or None
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Ödeme Kaydı (onaylandi → odendi)
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/pay", name="hbf_pay")
async def hbf_pay(
    hbf_id: int,
    pay_date: str = Form(""),
    payment_method: str = Form("banka"),
    bank_account_id: int = Form(None),
    cash_book_id: int = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403)
    hbf = db.query(HBF).get(hbf_id)
    if not hbf or hbf.status != "onaylandi":
        raise HTTPException(status_code=404)

    pdate = _date.fromisoformat(pay_date) if pay_date else _date.today()
    emp_name = hbf.employee.name if hbf.employee else "Çalışan"
    desc = f"HBF {hbf.hbf_no} — {emp_name}"

    # GeneralExpense kaydı
    cat_id = _hbf_expense_category(db)
    ge = GeneralExpense(
        category_id=cat_id,
        employee_id=hbf.employee_id,
        description=f"{hbf.hbf_no}: {hbf.title}",
        amount=hbf.total_amount,
        expense_date=pdate,
        source="hbf",
        created_by=current_user.id,
    )
    db.add(ge)
    db.flush()
    hbf.general_expense_id = ge.id

    # Kasa/Banka hareketi
    if payment_method == "nakit" and cash_book_id:
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=pdate,
            entry_type="cikis", amount=hbf.total_amount, description=desc,
        ))
    elif payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=pdate,
            movement_type="cikis", amount=hbf.total_amount, description=desc,
        ))

    hbf.status = "odendi"
    hbf.paid_at = pdate
    hbf.payment_method = payment_method
    hbf.bank_account_id = bank_account_id if payment_method == "banka" else None
    hbf.cash_book_id = cash_book_id if payment_method == "nakit" else None
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Sil (sadece taslak)
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/delete", name="hbf_delete")
async def hbf_delete(
    hbf_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if hbf and (hbf.created_by == current_user.id or current_user.is_admin):
        if hbf.status == "taslak":
            db.delete(hbf)
            db.commit()
    return RedirectResponse(url="/hbf", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Belge Yükle / Sil
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/upload", name="hbf_upload")
async def hbf_upload(
    hbf_id: int,
    file: UploadFile = File(...),
    row_id: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if not hbf:
        raise HTTPException(status_code=404)
    if not (current_user.is_admin or current_user.is_approver or hbf.created_by == current_user.id):
        raise HTTPException(status_code=403)

    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen dosya türü: {ext}")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    hbf_dir = os.path.join(UPLOAD_DIR, str(hbf_id))
    os.makedirs(hbf_dir, exist_ok=True)
    dest = os.path.join(hbf_dir, safe_name)

    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    try:
        attachments = json.loads(hbf.attachments_json or "[]")
    except Exception:
        attachments = []

    new_att = {
        "filename": safe_name,
        "original": file.filename,
        "uploaded_at": _date.today().isoformat(),
    }
    if row_id:
        new_att["row_id"] = row_id
        # Aynı satıra ait önceki dosyayı sil (replace semantics)
        for old in [a for a in attachments if a.get("row_id") == row_id]:
            old_path = os.path.join(UPLOAD_DIR, str(hbf_id), old["filename"])
            if os.path.exists(old_path):
                os.remove(old_path)
        attachments = [a for a in attachments if a.get("row_id") != row_id]

    attachments.append(new_att)
    hbf.attachments_json = json.dumps(attachments, ensure_ascii=False)
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{hbf_id}/attachment/{filename}/delete", name="hbf_attachment_delete")
async def hbf_attachment_delete(
    hbf_id: int,
    filename: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hbf = db.query(HBF).get(hbf_id)
    if not hbf:
        raise HTTPException(status_code=404)
    if not (current_user.is_admin or hbf.created_by == current_user.id):
        raise HTTPException(status_code=403)

    try:
        attachments = json.loads(hbf.attachments_json or "[]")
    except Exception:
        attachments = []
    attachments = [a for a in attachments if a["filename"] != filename]
    hbf.attachments_json = json.dumps(attachments, ensure_ascii=False)
    db.commit()

    # Dosyayı diskten sil
    fpath = os.path.join(UPLOAD_DIR, str(hbf_id), filename)
    if os.path.exists(fpath):
        os.remove(fpath)
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)
