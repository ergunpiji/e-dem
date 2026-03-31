"""
E-dem — Talep yönetimi router'ı
PM:    Yeni talep oluştur, referanslarım
Admin: Tüm referanslar
E-dem: Gelen referanslar, durum güncelle
"""

import json
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user
from database import generate_ref_no, get_db
from models import (
    Customer, EventType, REQUEST_STATUSES, REQUEST_TABS, TR_CITIES,
    SUPPLIER_TYPES, Service, SERVICE_CATEGORIES, Request as ReqModel, User, Venue, _uuid, _now,
)

router = APIRouter(prefix="/requests", tags=["requests"])
from templates_config import templates


def _check_pm_or_admin(current_user: User):
    if current_user.role not in ("admin", "project_manager"):
        raise HTTPException(status_code=403, detail="Bu sayfa Proje Yöneticilerine özeldir.")


def _check_edem_or_admin(current_user: User):
    if current_user.role not in ("admin", "e_dem"):
        raise HTTPException(status_code=403, detail="Bu sayfa E-dem kullanıcılarına özeldir.")


# ---------------------------------------------------------------------------
# Listeler
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="requests_list")
async def requests_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: str = "",
):
    """Rol bazlı talep listesi"""
    query = db.query(ReqModel)

    if current_user.role == "project_manager":
        query = query.filter(ReqModel.created_by == current_user.id)
        page_title = "Referanslarım"
    elif current_user.role == "e_dem":
        query = query.filter(
            ReqModel.status.in_(["pending", "in_progress", "venues_contacted", "budget_ready"])
        )
        page_title = "Gelen Referanslar"
    else:
        page_title = "Tüm Referanslar"

    if status_filter:
        query = query.filter(ReqModel.status == status_filter)

    requests_all = query.order_by(ReqModel.created_at.desc()).all()

    return templates.TemplateResponse(
        "requests/list.html",
        {
            "request":          request,
            "current_user":     current_user,
            "requests":         requests_all,
            "page_title":       page_title,
            "statuses":         REQUEST_STATUSES,
            "status_filter":    status_filter,
        },
    )


# ---------------------------------------------------------------------------
# Yeni Talep Oluştur
# ---------------------------------------------------------------------------

@router.get("/api/customer-contacts/{customer_id}", name="customer_contacts_api")
async def get_customer_contacts(
    customer_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return JSONResponse([])
    return JSONResponse(customer.contacts)


@router.get("/new", response_class=HTMLResponse, name="requests_new")
async def requests_new(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_pm_or_admin(current_user)
    customers   = db.query(Customer).order_by(Customer.name).all()
    venues      = db.query(Venue).filter(Venue.active == True).order_by(Venue.name).all()
    event_types = db.query(EventType).filter(EventType.active == True).order_by(EventType.sort_order).all()
    services    = db.query(Service).filter(Service.active == True).order_by(Service.category, Service.name).all()
    # Group services by category
    services_by_cat: dict = {}
    for svc in services:
        services_by_cat.setdefault(svc.category, []).append(svc.to_dict())
    custom_cats = []
    try:
        from models import CustomCategory
        custom_cats = db.query(CustomCategory).all()
    except Exception:
        pass

    return templates.TemplateResponse(
        "requests/form.html",
        {
            "request":          request,
            "current_user":     current_user,
            "req":              None,
            "page_title":       "Yeni Talep Oluştur",
            "customers":        customers,
            "venues":           venues,
            "event_types":      event_types,
            "services_by_cat":  services_by_cat,
            "service_categories": SERVICE_CATEGORIES,
            "tr_cities":        TR_CITIES,
            "request_tabs":     REQUEST_TABS,
            "supplier_types":   SUPPLIER_TYPES,
            "custom_cats":      custom_cats,
            "error":            None,
        },
    )


@router.post("/new", name="requests_create")
async def requests_create(
    request: Request,
    client_name:          str = Form(...),
    customer_id:          str = Form(""),
    event_name:           str = Form(...),
    event_type:           str = Form("yi"),   # EventType.code
    cities_json:          str = Form("[]"),
    attendee_count:       str = Form("0"),
    check_in:             str = Form(""),
    check_out:            str = Form(""),
    accom_check_in:       str = Form(""),
    accom_check_out:      str = Form(""),
    quote_deadline:       str = Form(""),
    description:          str = Form(""),
    notes:                str = Form(""),
    items_json:           str = Form("{}"),
    preferred_venues_json: str = Form("[]"),
    contact_person_json:  str = Form("{}"),
    action:               str = Form("draft"),  # 'draft' veya 'send'
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_pm_or_admin(current_user)

    # Müşteri kodu
    customer_code = "xxx"
    if customer_id:
        cust = db.query(Customer).filter(Customer.id == customer_id).first()
        if cust:
            customer_code = cust.code

    # Resolve event_type_code
    event_type_code = event_type  # already a code like 'yi'

    if action == "send":
        ref_status = "pending"
    elif action == "direct":
        ref_status = "in_progress"
    else:
        ref_status = "draft"
    ref_no = generate_ref_no(db, event_type_code, customer_code, check_in)

    # cities JSON → city string (geriye uyumluluk)
    try:
        cities_list = json.loads(cities_json or "[]")
    except Exception:
        cities_list = []
    city_str = ", ".join(cities_list)

    req = ReqModel(
        id=_uuid(),
        request_no=ref_no,
        client_name=client_name.strip(),
        customer_id=customer_id or None,
        event_name=event_name.strip(),
        event_type=event_type_code,
        city=city_str,
        cities_json=cities_json,
        attendee_count=int(attendee_count) if attendee_count.isdigit() else 0,
        check_in=check_in or None,
        check_out=check_out or None,
        accom_check_in=accom_check_in or None,
        accom_check_out=accom_check_out or None,
        quote_deadline=quote_deadline or None,
        status=ref_status,
        items_json=items_json,
        description=description.strip(),
        notes=notes.strip(),
        preferred_venues_json=preferred_venues_json,
        selected_venues_json="[]",
        contact_person_json=contact_person_json,
        created_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(req)
    db.commit()
    return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Detay
# ---------------------------------------------------------------------------

@router.get("/{req_id}", response_class=HTMLResponse, name="requests_detail")
async def requests_detail(
    req_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = (db.query(ReqModel)
             .options(joinedload(ReqModel.budgets))
             .filter(ReqModel.id == req_id)
             .first())
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    venues      = db.query(Venue).filter(Venue.active == True).all()
    event_types = db.query(EventType).order_by(EventType.sort_order).all()
    et_map      = {et.code: et.label for et in event_types}
    can_edit_status = current_user.role in ("admin", "e_dem")
    can_edit_req    = (current_user.role in ("admin", "project_manager") and
                       (req.created_by == current_user.id or current_user.role == "admin"))
    # PM kendi talebini direkt yönetiyorsa (in_progress) RFQ ve bütçe oluşturabilir
    can_direct_manage = (
        current_user.role in ("admin", "project_manager") and
        req.status in ("in_progress", "venues_contacted", "budget_ready") and
        (req.created_by == current_user.id or current_user.role == "admin")
    )

    # venue id → supplier_type map (RFQ filtrelemesi için)
    venues_map = {v.id: {"name": v.name, "city": v.city,
                          "supplier_type": v.supplier_type,
                          "contacts": v.contacts} for v in venues}

    # Her bütçe için rows_by_section hesapla (tab karşılaştırması için)
    budgets_data = []
    for b in req.budgets:
        rbs = {}
        for row in b.rows:
            sec = row.get("section", "other")
            rbs.setdefault(sec, []).append(row)
        budgets_data.append({"budget": b, "rows_by_section": rbs})

    return templates.TemplateResponse(
        "requests/detail.html",
        {
            "request":          request,
            "current_user":     current_user,
            "req":              req,
            "page_title":       req.request_no,
            "statuses":         REQUEST_STATUSES,
            "venues":           venues,
            "venues_map":       venues_map,
            "event_types":      event_types,
            "et_map":           et_map,
            "can_edit_status":  can_edit_status,
            "can_edit_req":     can_edit_req,
            "can_direct_manage": can_direct_manage,
            "request_tabs":     REQUEST_TABS,
            "budgets_data":     budgets_data,
        },
    )


# ---------------------------------------------------------------------------
# Düzenleme
# ---------------------------------------------------------------------------

@router.get("/{req_id}/edit", response_class=HTMLResponse, name="requests_edit")
async def requests_edit(
    req_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_pm_or_admin(current_user)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    # Admin her talebi düzenleyebilir; PM sadece kendi talebini
    if current_user.role != "admin" and req.created_by != current_user.id:
        return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)

    customers   = db.query(Customer).order_by(Customer.name).all()
    venues      = db.query(Venue).filter(Venue.active == True).order_by(Venue.name).all()
    event_types = db.query(EventType).filter(EventType.active == True).order_by(EventType.sort_order).all()
    services    = db.query(Service).filter(Service.active == True).order_by(Service.category, Service.name).all()
    services_by_cat: dict = {}
    for svc in services:
        services_by_cat.setdefault(svc.category, []).append(svc.to_dict())

    return templates.TemplateResponse(
        "requests/form.html",
        {
            "request":          request,
            "current_user":     current_user,
            "req":              req,
            "page_title":       f"{req.request_no} — Düzenle",
            "customers":        customers,
            "venues":           venues,
            "event_types":      event_types,
            "services_by_cat":  services_by_cat,
            "service_categories": SERVICE_CATEGORIES,
            "tr_cities":        TR_CITIES,
            "request_tabs":     REQUEST_TABS,
            "supplier_types":   SUPPLIER_TYPES,
            "custom_cats":      [],
            "error":            None,
        },
    )


@router.post("/{req_id}/edit", name="requests_update")
async def requests_update(
    req_id: str,
    request: Request,
    client_name:          str = Form(...),
    customer_id:          str = Form(""),
    event_name:           str = Form(...),
    event_type:           str = Form("yi"),
    cities_json:          str = Form("[]"),
    attendee_count:       str = Form("0"),
    check_in:             str = Form(""),
    check_out:            str = Form(""),
    accom_check_in:       str = Form(""),
    accom_check_out:      str = Form(""),
    quote_deadline:       str = Form(""),
    description:          str = Form(""),
    notes:                str = Form(""),
    items_json:           str = Form("{}"),
    preferred_venues_json: str = Form("[]"),
    contact_person_json:  str = Form("{}"),
    action:               str = Form("draft"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_pm_or_admin(current_user)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)
    if current_user.role != "admin" and req.created_by != current_user.id:
        return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)

    try:
        cities_list = json.loads(cities_json or "[]")
    except Exception:
        cities_list = []

    req.client_name           = client_name.strip()
    req.customer_id           = customer_id or None
    req.event_name            = event_name.strip()
    req.event_type            = event_type
    req.cities_json           = cities_json
    req.city                  = ", ".join(cities_list)
    req.attendee_count        = int(attendee_count) if attendee_count.isdigit() else 0
    req.check_in              = check_in or None
    req.check_out             = check_out or None
    req.accom_check_in        = accom_check_in or None
    req.accom_check_out       = accom_check_out or None
    req.quote_deadline        = quote_deadline or None
    req.description           = description.strip()
    req.notes                 = notes.strip()
    req.items_json            = items_json
    req.preferred_venues_json = preferred_venues_json
    req.contact_person_json   = contact_person_json
    req.updated_at            = _now()

    if action == "send" and req.status == "draft":
        req.status = "pending"
    elif action == "direct" and req.status == "draft":
        req.status = "in_progress"

    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Durum güncelleme (E-dem)
# ---------------------------------------------------------------------------

@router.post("/{req_id}/status", name="requests_update_status")
async def requests_update_status(
    req_id: str,
    new_status: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    # E-dem/Admin: her duruma geçebilir
    # PM direkt yönetim: sadece kendi talebi ve belirli statüler
    is_edem_or_admin = current_user.role in ("admin", "e_dem")
    is_pm_direct = (
        current_user.role == "project_manager" and
        req.created_by == current_user.id and
        req.status in ("in_progress", "venues_contacted", "budget_ready")
    )
    if not is_edem_or_admin and not is_pm_direct:
        raise HTTPException(status_code=403, detail="Yetkisiz erişim.")

    req.status     = new_status
    req.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Silme
# ---------------------------------------------------------------------------

@router.post("/{req_id}/delete", name="requests_delete")
async def requests_delete(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_pm_or_admin(current_user)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if req and (req.status == "draft" or current_user.role == "admin"):
        db.delete(req)
        db.commit()
    return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)
