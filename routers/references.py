"""
Referanslar — iş/proje takibi
"""

from datetime import date, datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db, generate_ref_no
from models import Reference, Customer, Invoice, User, EVENT_TYPES
from templates_config import templates

router = APIRouter(prefix="/references", tags=["references"])


@router.get("", response_class=HTMLResponse, name="references_list")
async def references_list(
    request: Request,
    q: str = "",
    status_filter: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Reference)
    if status_filter:
        query = query.filter(Reference.status == status_filter)
    if q:
        query = query.filter(
            Reference.title.ilike(f"%{q}%") |
            Reference.ref_no.ilike(f"%{q}%")
        )
    refs = query.order_by(Reference.created_at.desc()).all()
    customers = db.query(Customer).order_by(Customer.name).all()
    return templates.TemplateResponse(
        "references/list.html",
        {
            "request": request,
            "current_user": current_user,
            "refs": refs,
            "customers": customers,
            "q": q,
            "status_filter": status_filter,
            "page_title": "Referanslar",
        },
    )


@router.get("/new", response_class=HTMLResponse, name="reference_new_get")
async def reference_new_get(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customers = db.query(Customer).filter(
        Customer.code.is_not(None),
        Customer.active == True,  # noqa: E712
    ).order_by(Customer.name).all()
    return templates.TemplateResponse(
        "references/form.html",
        {
            "request": request,
            "current_user": current_user,
            "ref": None,
            "customers": customers,
            "event_types": EVENT_TYPES,
            "page_title": "Yeni Referans",
        },
    )


@router.post("/new", name="reference_new_post")
async def reference_new_post(
    request: Request,
    ref_no: str = Form(...),
    customer_id: int = Form(None),
    title: str = Form(...),
    event_type: str = Form("diger"),
    check_in: str = Form(""),
    check_out: str = Form(""),
    notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ref_no = ref_no.strip().upper()
    customers = db.query(Customer).filter(
        Customer.code.is_not(None),
        Customer.active == True,  # noqa: E712
    ).order_by(Customer.name).all()

    # Benzersizlik kontrolü
    existing = db.query(Reference).filter(Reference.ref_no == ref_no).first()
    if existing:
        return templates.TemplateResponse(
            "references/form.html",
            {
                "request": request, "current_user": current_user,
                "ref": None, "customers": customers,
                "event_types": EVENT_TYPES, "page_title": "Yeni Referans",
                "error": f'"{ref_no}" kodu zaten kullanımda. Lütfen farklı bir kod girin.',
                "form_data": {"ref_no": ref_no, "customer_id": customer_id, "title": title,
                              "event_type": event_type, "check_in": check_in,
                              "check_out": check_out, "notes": notes},
            },
            status_code=422,
        )

    ci = date.fromisoformat(check_in) if check_in else date.today()
    ref = Reference(
        ref_no=ref_no,
        customer_id=customer_id,
        title=title.strip(),
        event_type=event_type,
        check_in=ci,
        check_out=date.fromisoformat(check_out) if check_out else ci,
        status="aktif",
        notes=notes.strip(),
        created_by=current_user.id,
    )
    db.add(ref)
    db.commit()
    return RedirectResponse(url=f"/references/{ref.id}", status_code=status.HTTP_302_FOUND)


@router.get("/{ref_id}", response_class=HTMLResponse, name="reference_detail")
async def reference_detail(
    ref_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ref = db.query(Reference).get(ref_id)
    if not ref:
        raise HTTPException(status_code=404)
    invoices = db.query(Invoice).filter(Invoice.ref_id == ref_id).order_by(Invoice.invoice_date.desc()).all()

    total_kesilen = sum(i.amount for i in invoices if i.invoice_type == "kesilen")
    total_gelen = sum(i.amount for i in invoices if i.invoice_type == "gelen")

    return templates.TemplateResponse(
        "references/detail.html",
        {
            "request": request,
            "current_user": current_user,
            "ref": ref,
            "invoices": invoices,
            "total_kesilen": total_kesilen,
            "total_gelen": total_gelen,
            "kar": total_kesilen - total_gelen,
            "page_title": f"Referans — {ref.ref_no}",
        },
    )


@router.get("/{ref_id}/edit", response_class=HTMLResponse, name="reference_edit_get")
async def reference_edit_get(
    ref_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ref = db.query(Reference).get(ref_id)
    if not ref:
        raise HTTPException(status_code=404)
    customers = db.query(Customer).order_by(Customer.name).all()
    return templates.TemplateResponse(
        "references/form.html",
        {
            "request": request,
            "current_user": current_user,
            "ref": ref,
            "customers": customers,
            "event_types": EVENT_TYPES,
            "page_title": f"Düzenle — {ref.ref_no}",
        },
    )


@router.post("/{ref_id}/edit", name="reference_edit_post")
async def reference_edit_post(
    request: Request,
    ref_id: int,
    ref_no: str = Form(...),
    customer_id: int = Form(None),
    title: str = Form(...),
    event_type: str = Form("diger"),
    check_in: str = Form(""),
    check_out: str = Form(""),
    notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ref = db.query(Reference).get(ref_id)
    if not ref:
        raise HTTPException(status_code=404)

    ref_no = ref_no.strip().upper()
    # Benzersizlik kontrolü — kendi kaydı hariç
    conflict = db.query(Reference).filter(
        Reference.ref_no == ref_no, Reference.id != ref_id
    ).first()
    if conflict:
        customers = db.query(Customer).order_by(Customer.name).all()
        return templates.TemplateResponse(
            "references/form.html",
            {
                "request": request, "current_user": current_user,
                "ref": ref, "customers": customers,
                "event_types": EVENT_TYPES,
                "page_title": f"Düzenle — {ref.ref_no}",
                "error": f'"{ref_no}" kodu başka bir referansta kullanımda.',
            },
            status_code=422,
        )

    ref.ref_no = ref_no
    ref.customer_id = customer_id
    ref.title = title.strip()
    ref.event_type = event_type
    ref.check_in = date.fromisoformat(check_in) if check_in else ref.check_in
    ref.check_out = date.fromisoformat(check_out) if check_out else ref.check_out
    ref.notes = notes.strip()
    db.commit()
    return RedirectResponse(url=f"/references/{ref_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{ref_id}/status", name="reference_status")
async def reference_status(
    ref_id: int,
    new_status: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ref = db.query(Reference).get(ref_id)
    if not ref:
        raise HTTPException(status_code=404)
    if new_status in ("aktif", "tamamlandi", "iptal"):
        ref.status = new_status
        db.commit()
    return RedirectResponse(url=f"/references/{ref_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{ref_id}/delete", name="reference_delete")
async def reference_delete(
    ref_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ref = db.query(Reference).get(ref_id)
    if ref:
        db.delete(ref)
        db.commit()
    return RedirectResponse(url="/references", status_code=status.HTTP_302_FOUND)
