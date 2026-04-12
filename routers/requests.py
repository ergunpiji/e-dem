"""
E-dem — Talep yönetimi router'ı
PM:    Yeni talep oluştur, referanslarım
Admin: Tüm referanslar
E-dem: Gelen referanslar, durum güncelle
"""

import io
import json
import os
import unicodedata
import urllib.parse
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user
from database import generate_ref_no, get_db
from models import (
    Budget, Customer, CustomCategory, EmailTemplate, EventType, REQUEST_STATUSES, REQUEST_TABS,
    TR_CITIES, SUPPLIER_TYPES, Service, SERVICE_CATEGORIES, Request as ReqModel, User, Venue,
    _uuid, _now,
)

router = APIRouter(prefix="/requests", tags=["requests"])
from templates_config import templates


def _check_pm_or_admin(current_user: User):
    if current_user.role not in ("admin", "mudur", "yonetici", "asistan", "project_manager"):
        raise HTTPException(status_code=403, detail="Bu sayfa Proje Yöneticilerine özeldir.")


def _get_subtree_ids(user_id: str, db: Session) -> list[str]:
    """Kullanıcının tüm astları (doğrudan + dolaylı) — BFS."""
    result: list[str] = []
    queue = [user_id]
    while queue:
        curr = queue.pop(0)
        subs = [r.id for r in db.query(User).filter(User.manager_id == curr).all()]
        for sid in subs:
            if sid not in result:
                result.append(sid)
                queue.append(sid)
    return result


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
    search: str = "",
    view: str = "",
):
    """Rol bazlı talep listesi"""
    query = db.query(ReqModel)

    # Special views take priority over role-based filtering
    if view == "ongoing":
        query = query.filter(
            ReqModel.status == "confirmed",
            ReqModel.confirmed_budget_id.isnot(None),
        )
        page_title = "Aktif İşler"
    elif view == "completed":
        query = query.filter(ReqModel.status == "completed")
        page_title = "Tamamlanan İşler"
    elif view == "closing":
        query = query.filter(ReqModel.status == "closing")
        page_title = "Kapama Onayında"
    elif view == "closed":
        query = query.filter(ReqModel.status == "closed")
        page_title = "Kapatılan Dosyalar"
    elif view == "cancelled":
        query = query.filter(ReqModel.status == "cancelled")
        page_title = "İptal İşler"
    elif view == "pending_work":
        # Yeni & işlemdeki talepler — henüz müşteriye teklif verilmemiş
        base = ["pending", "in_progress", "venues_contacted", "budget_ready"]
        if current_user.role == "mudur" and current_user.team_id:
            team_ids = [u.id for u in db.query(User).filter(
                User.team_id == current_user.team_id, User.active == True).all()]
            query = query.filter(
                ReqModel.created_by.in_(team_ids + [current_user.id]),
                ReqModel.status.in_(base),
            )
        elif current_user.role == "yonetici":
            sub_ids = _get_subtree_ids(current_user.id, db)
            query = query.filter(
                ReqModel.created_by.in_([current_user.id] + sub_ids),
                ReqModel.status.in_(base),
            )
        elif current_user.role == "asistan":
            query = query.filter(
                ReqModel.created_by == current_user.id,
                ReqModel.status.in_(base),
            )
        else:
            query = query.filter(ReqModel.status.in_(base))
        page_title = "Yeni & İşlemdeki Talepler"
    elif view == "awaiting":
        # Teklif verilmiş, müşteri kararı bekleniyor
        base = ["offer_sent", "revision", "postponed"]
        if current_user.role == "mudur" and current_user.team_id:
            team_ids = [u.id for u in db.query(User).filter(
                User.team_id == current_user.team_id, User.active == True).all()]
            query = query.filter(
                ReqModel.created_by.in_(team_ids + [current_user.id]),
                ReqModel.status.in_(base),
            )
        elif current_user.role == "yonetici":
            sub_ids = _get_subtree_ids(current_user.id, db)
            query = query.filter(
                ReqModel.created_by.in_([current_user.id] + sub_ids),
                ReqModel.status.in_(base),
            )
        elif current_user.role == "asistan":
            query = query.filter(
                ReqModel.created_by == current_user.id,
                ReqModel.status.in_(base),
            )
        else:
            query = query.filter(ReqModel.status.in_(base))
        page_title = "Karar Bekleyenler"
    elif current_user.role == "mudur":
        # mudur: takımındaki tüm üyelerin referansları
        if current_user.team_id:
            team_member_ids = [
                u.id for u in db.query(User).filter(
                    User.team_id == current_user.team_id,
                    User.active == True,
                ).all()
            ]
            query = query.filter(ReqModel.created_by.in_(team_member_ids + [current_user.id]))
        # takımsız mudur → tüm referanslar (fallback)
        page_title = "Takım Referansları"
    elif current_user.role == "yonetici":
        # yonetici: kendi + tüm astlarının referansları
        sub_ids = _get_subtree_ids(current_user.id, db)
        query = query.filter(ReqModel.created_by.in_([current_user.id] + sub_ids))
        page_title = "Referanslarım"
    elif current_user.role == "asistan":
        # asistan: sadece kendi referansları
        query = query.filter(ReqModel.created_by == current_user.id)
        page_title = "Referanslarım"
    elif current_user.role == "e_dem":
        query = query.filter(
            ReqModel.status.in_(["pending", "in_progress", "venues_contacted", "budget_ready",
                                  "offer_sent", "revision"])
        )
        page_title = "Gelen Referanslar"
    else:
        # admin, mudur, muhasebe_muduru → tüm referanslar
        page_title = "Tüm Referanslar"

    if status_filter:
        query = query.filter(ReqModel.status == status_filter)

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            ReqModel.request_no.ilike(term) |
            ReqModel.event_name.ilike(term) |
            ReqModel.client_name.ilike(term)
        )

    requests_all = query.order_by(ReqModel.created_at.desc()).all()

    # For ongoing view, resolve confirmed venue name from budget
    confirmed_venue_map = {}
    if view == "ongoing":
        for req in requests_all:
            if req.confirmed_budget_id:
                bgt = db.query(Budget).filter(Budget.id == req.confirmed_budget_id).first()
                if bgt:
                    confirmed_venue_map[req.id] = bgt.venue_name

    return templates.TemplateResponse(
        "requests/list.html",
        {
            "request":               request,
            "current_user":          current_user,
            "requests":              requests_all,
            "page_title":            page_title,
            "statuses":              REQUEST_STATUSES,
            "status_filter":         status_filter,
            "search":                search,
            "view":                  view,
            "confirmed_venue_map":   confirmed_venue_map,
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
             .options(joinedload(ReqModel.budgets), joinedload(ReqModel.invoices))
             .filter(ReqModel.id == req_id)
             .first())
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    venues      = db.query(Venue).filter(Venue.active == True).all()
    event_types = db.query(EventType).order_by(EventType.sort_order).all()
    et_map      = {et.code: et.label for et in event_types}
    can_edit_status = current_user.role in ("admin", "e_dem")
    # mudur tüm referansları düzenleyebilir; yonetici/asistan sadece kendi talebini
    can_edit_req = (
        current_user.role == "admin" or
        (current_user.role in ("mudur", "yonetici") and
         (req.created_by == current_user.id or current_user.role == "mudur")) or
        (current_user.role == "asistan" and req.created_by == current_user.id)
    )
    # Teklif gönderme ve bütçe onayı: admin, mudur, yonetici (asistan yapamaz)
    can_send_offer    = current_user.role in ("admin", "mudur", "yonetici")
    can_approve_budget = current_user.role in ("admin", "mudur", "yonetici")
    # Bütçeye fiyat girme: asistan dahil tüm PM tarafı
    can_price_budget  = current_user.role in ("admin", "mudur", "yonetici", "asistan")
    # PM kendi talebini direkt yönetiyorsa (in_progress) RFQ ve bütçe oluşturabilir
    can_direct_manage = (
        current_user.role in ("admin", "mudur", "yonetici") and
        req.status in ("in_progress", "venues_contacted", "budget_ready") and
        (req.created_by == current_user.id or current_user.role in ("admin", "mudur"))
    )
    # Bütçe oluşturma/düzenleme: asistan da yapabilir (durum güncelleme/RFQ hariç)
    can_budget_ops = (
        can_direct_manage or (
            current_user.role == "asistan" and
            req.status in ("in_progress", "venues_contacted", "budget_ready")
        )
    )

    # Onay bekleyen kişi bilgisi
    def _find_next_approver(user_id: str | None) -> User | None:
        """Bir kullanıcının zincirindeki ilk mudur'u bul."""
        if not user_id:
            return None
        visited: set = set()
        current = db.query(User).filter(User.id == user_id).first()
        while current and current.manager_id and current.manager_id not in visited:
            visited.add(current.manager_id)
            mgr = db.query(User).filter(User.id == current.manager_id, User.active == True).first()
            if not mgr:
                break
            if mgr.role in ("mudur", "admin"):
                return mgr
            current = mgr
        return db.query(User).filter(User.role == "mudur", User.active == True).first()

    def _find_gm_approver() -> User | None:
        users = db.query(User).filter(User.role == "mudur", User.active == True).all()
        best, best_grade = None, 999
        for u in users:
            if u.org_title and u.org_title.grade < best_grade:
                best_grade = u.org_title.grade
                best = u
        return best or db.query(User).filter(User.role == "mudur", User.active == True).first()

    def _find_muhasebe_muduru() -> User | None:
        return db.query(User).filter(User.role == "muhasebe_muduru", User.active == True).first()

    # Kapama için beklenen onaylayıcı
    closure_pending_approver: User | None = None
    if req.closure_request and req.closure_request.status == "pending_manager":
        closure_pending_approver = _find_next_approver(req.closure_request.submitted_by)
    elif req.closure_request and req.closure_request.status == "pending_gm":
        closure_pending_approver = _find_gm_approver()
    elif req.closure_request and req.closure_request.status == "pending_finance":
        closure_pending_approver = _find_muhasebe_muduru()

    # Bütçeler için beklenen onaylayıcı (pending_manager)
    budget_pending_approvers: dict = {}  # budget_id → User
    for b in req.budgets:
        if b.budget_status == "pending_manager":
            budget_pending_approvers[b.id] = _find_next_approver(req.created_by)

    # venue id → supplier_type map (RFQ filtrelemesi için)
    venues_map = {v.id: {"name": v.name, "city": v.city,
                          "supplier_type": v.supplier_type,
                          "contacts": v.contacts} for v in venues}

    # Her bütçe için rows_by_section + totals hesapla
    _CURR_SYMS = {"TRY": "₺", "EUR": "€", "USD": "$"}

    def _budget_totals(b):
        SECTION_ORDER = ["accommodation", "meeting", "fb", "teknik", "dekor", "transfer", "tasarim", "other"]
        offer_curr  = b.offer_currency or "TRY"
        ex_rates    = b.exchange_rates  # {'EUR': 38.5, 'USD': 32.1}
        offer_rate  = float(ex_rates.get(offer_curr, 1.0) or 1.0) if offer_curr != "TRY" else 1.0
        offer_sym   = _CURR_SYMS.get(offer_curr, offer_curr)

        sec_totals = {}
        cost_ex = sale_ex = vat_total = 0.0
        for row in b.rows:
            if row.get("is_service_fee") or row.get("is_accommodation_tax"):
                continue
            sec      = row.get("section", "other")
            qty      = float(row.get("qty", 1)  or 1)
            nts      = float(row.get("nights", 1) or 1)
            cost     = float(row.get("cost_price", 0) or 0)
            sale     = float(row.get("sale_price", 0) or 0)
            vat      = float(row.get("vat_rate", 0) or 0)
            row_curr = row.get("currency", "TRY") or "TRY"
            row_rate = float(ex_rates.get(row_curr, 1.0) or 1.0) if row_curr != "TRY" else 1.0
            # Her satırı offer_currency'ye çevir: TRY'ye çevir, sonra offer_currency'ye
            # row_curr → TRY: × row_rate; TRY → offer_curr: ÷ offer_rate
            conv = (row_rate / offer_rate) if offer_rate else 1.0
            cost_sub = cost * qty * nts * conv
            sale_sub = sale * qty * nts * conv
            cost_ex  += cost_sub
            sale_ex  += sale_sub
            vat_total += sale_sub * (vat / 100)
            if sec not in sec_totals:
                sec_totals[sec] = {"cost": 0.0, "sale": 0.0}
            sec_totals[sec]["cost"] += cost_sub
            sec_totals[sec]["sale"] += sale_sub
        sf_pct    = float(b.service_fee_pct or 0)
        sf_amount = round(sale_ex * sf_pct / 100, 2)
        sf_vat    = round(sf_amount * 0.20, 2)
        grand     = round(sale_ex + vat_total + sf_amount + sf_vat, 2)  # offer_currency cinsinden
        grand_try = round(grand * offer_rate, 2)                         # TRY cinsinden
        base      = sale_ex + sf_amount
        margin    = round((sale_ex - cost_ex + sf_amount) / base * 100, 1) if base > 0 else 0.0
        # sections listesi: SECTION_ORDER sırasına göre sadece veri olanlar
        ordered_secs = [(s, sec_totals[s]) for s in SECTION_ORDER if s in sec_totals]
        return {
            "cost_ex":        cost_ex,
            "sale_ex":        sale_ex,
            "vat":            vat_total,
            "sf_pct":         sf_pct,
            "sf_amount":      sf_amount,
            "sf_vat":         sf_vat,
            "grand":          grand,       # offer_currency cinsinden
            "grand_try":      grand_try,   # TRY cinsinden (karşılaştırma + alt satır için)
            "margin":         margin,
            "sections":       ordered_secs,
            "offer_currency": offer_curr,
            "offer_sym":      offer_sym,
            "offer_rate":     offer_rate,
        }

    budgets_data = []
    for b in req.budgets:
        rbs = {}
        for row in b.rows:
            if row.get("is_service_fee") or row.get("is_accommodation_tax"):
                continue
            sec = row.get("section", "other")
            rbs.setdefault(sec, []).append(row)
        budgets_data.append({"budget": b, "rows_by_section": rbs, "totals": _budget_totals(b)})

    # Özet sekmesi için tüm benzersiz sectionlar (en az bir bütçede var olanlar)
    all_sections_set = []
    seen = set()
    for bd in budgets_data:
        for sec, _ in bd["totals"]["sections"]:
            if sec not in seen:
                seen.add(sec)
                all_sections_set.append(sec)

    customer = (db.query(Customer).filter(Customer.id == req.customer_id).first()
                if req.customer_id else None)

    # E-posta şablonları — JS'e aktarılacak {slug: {subject_tpl, body_tpl}}
    from models import Settings as SettingsModel
    settings = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
    _email_tpls_raw = db.query(EmailTemplate).filter(EmailTemplate.active == True).all()
    email_templates_json = {
        t.slug: {"subject_tpl": t.subject_tpl, "body_tpl": t.body_tpl}
        for t in _email_tpls_raw
    }
    # Settings değerleri (imza vb.)
    settings_ctx = {
        "company_name":    settings.company_name    if settings else "",
        "company_email":   settings.company_email   if settings else "",
        "company_phone":   settings.company_phone   if settings else "",
        "email_signature": settings.email_signature if settings else "",
    }

    # Email taslakları için bütçe + venue kontakt bilgileri
    # İsim bazlı fallback lookup için: {normalize(name): contacts}
    _venues_by_name = {
        v["name"].strip().lower(): v.get("contacts", []) or []
        for v in venues_map.values()
    }

    budgets_json = []
    for b in req.budgets:
        contacts = []
        if b.venue_id and b.venue_id in venues_map:
            contacts = venues_map[b.venue_id].get("contacts", []) or []
        elif b.venue_name:
            # venue_id bağlantısı yoksa isme göre eşleştir
            contacts = _venues_by_name.get(b.venue_name.strip().lower(), [])
        budgets_json.append({
            "id":         b.id,
            "venue_name": b.venue_name or "",
            "venue_id":   b.venue_id or "",
            "contacts":   contacts,
            "status":     b.budget_status,
        })

    # ── Finansal veriler ──
    approved_invoices = [inv for inv in (req.invoices or []) if inv.status == "approved"]
    pending_invoices  = [inv for inv in (req.invoices or []) if inv.status == "pending"]
    rejected_invoices = [inv for inv in (req.invoices or []) if inv.status == "rejected"]
    # geriye uyumluluk — eski "active" kayıtlar da dahil
    active_invoices   = approved_invoices + [inv for inv in (req.invoices or []) if inv.status == "active"]

    invoice_ciro     = (sum(inv.amount for inv in active_invoices if inv.invoice_type == "kesilen")
                      - sum(inv.amount for inv in active_invoices if inv.invoice_type == "iade_kesilen"))
    invoice_komisyon = sum(inv.amount for inv in active_invoices if inv.invoice_type == "komisyon")
    invoice_maliyet  = (sum(inv.amount for inv in active_invoices if inv.invoice_type == "gelen")
                      - sum(inv.amount for inv in active_invoices if inv.invoice_type == "iade_gelen"))
    # Net maliyet: brüt gelen faturalar - komisyon geliri (komisyon maliyeti düşürür)
    invoice_net_maliyet = invoice_maliyet - invoice_komisyon
    invoice_kar      = invoice_ciro - invoice_net_maliyet

    # Belgesiz gelir/gider → ciro ve kar'a dahil et (HBF öncesi)
    from models import UndocumentedEntry as _UE
    _undoc = req.undocumented_entries or []
    _undoc_gelir = round(sum(e.amount for e in _undoc if e.entry_type == "gelir"), 2)
    _undoc_gider = round(sum(e.amount for e in _undoc if e.entry_type == "gider"), 2)
    invoice_ciro = round(invoice_ciro + _undoc_gelir - _undoc_gider, 2)
    invoice_kar  = round(invoice_kar  + _undoc_gelir - _undoc_gider, 2)

    confirmed_budget = None
    for b in req.budgets:
        if b.id == req.confirmed_budget_id:
            confirmed_budget = b
            break
    budget_sale_excl = confirmed_budget.grand_sale_excl_vat if confirmed_budget else 0.0
    budget_cost_excl = confirmed_budget.grand_cost_excl_vat if confirmed_budget else 0.0

    can_manage_invoices = current_user.role in ("admin", "muhasebe_muduru", "muhasebe")
    can_manage_undoc    = current_user.role in ("admin", "muhasebe_muduru", "muhasebe")
    # Fatura onayı: admin, mudur, yonetici, muhasebe_muduru
    can_approve_invoices = current_user.role in ("admin", "mudur", "yonetici", "muhasebe_muduru")
    # Admin referans taşıma için tüm referanslar
    all_requests = []
    if current_user.role == "admin":
        from models import Request as ReqModel2
        all_requests = db.query(ReqModel2).order_by(ReqModel2.created_at.desc()).limit(200).all()

    # ── HBF & Belgesiz ──
    expense_reports      = req.expense_reports or []
    undocumented_entries = _undoc
    undoc_gelir_total    = _undoc_gelir
    undoc_gider_total    = _undoc_gider

    # Onaylanmış HBF giderleri → karlılığa eksi etki (KDV hariç)
    hbf_approved_total = round(
        sum(r.grand_excl_vat for r in expense_reports if r.status == "approved"), 2
    )
    # Gerçek kar = fatura karı − onaylanan HBF giderleri
    invoice_kar = round(invoice_kar - hbf_approved_total, 2)
    from datetime import date as _date
    today = _date.today().strftime("%Y-%m-%d")

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
            "can_edit_status":   can_edit_status,
            "can_edit_req":      can_edit_req,
            "can_send_offer":    can_send_offer,
            "can_approve_budget": can_approve_budget,
            "can_price_budget":  can_price_budget,
            "can_direct_manage": can_direct_manage,
            "can_budget_ops":    can_budget_ops,
            "closure_pending_approver":  closure_pending_approver,
            "budget_pending_approvers":  budget_pending_approvers,
            "request_tabs":     REQUEST_TABS,
            "budgets_data":     budgets_data,
            "all_sections":     all_sections_set,
            "customer":         customer,
            "budgets_json":     budgets_json,
            # Finansal
            "active_invoices":       active_invoices,
            "pending_invoices":      pending_invoices,
            "rejected_invoices":     rejected_invoices,
            "invoice_ciro":          round(invoice_ciro, 2),
            "invoice_komisyon":      round(invoice_komisyon, 2),
            "invoice_maliyet":       round(invoice_maliyet, 2),
            "invoice_net_maliyet":   round(invoice_net_maliyet, 2),
            "invoice_kar":           round(invoice_kar, 2),
            "budget_sale_excl":  budget_sale_excl,
            "budget_cost_excl":  budget_cost_excl,
            "can_manage_invoices":   can_manage_invoices,
            "can_approve_invoices":  can_approve_invoices,
            "can_manage_undoc":      can_manage_undoc,
            "all_requests":          all_requests,
            "email_templates_json":  email_templates_json,
            "settings_ctx":          settings_ctx,
            "hbf_approved_total":      hbf_approved_total,
            # HBF & Belgesiz
            "expense_reports":        expense_reports,
            "undocumented_entries":   undocumented_entries,
            "undoc_gelir_total":      undoc_gelir_total,
            "undoc_gider_total":      undoc_gider_total,
            "today":                  today,
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

    # Admin ve mudur her talebi düzenleyebilir; yonetici/asistan sadece kendi talebini
    if current_user.role not in ("admin", "mudur") and req.created_by != current_user.id:
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
    if current_user.role not in ("admin", "mudur") and req.created_by != current_user.id:
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

    went_pending = False
    if action == "send" and req.status == "draft":
        req.status   = "pending"
        went_pending = True
    elif action == "direct" and req.status == "draft":
        req.status = "in_progress"

    db.commit()

    # Bildirim: tüm e_dem kullanıcılarına yeni referans
    if went_pending:
        from utils.notifications import create_notification
        edem_users = db.query(User).filter(
            User.role == "e_dem", User.active == True  # noqa: E712
        ).all()
        for eu in edem_users:
            create_notification(
                db,
                user_id    = eu.id,
                notif_type = "new_request",
                title      = f"Yeni referans — {req.request_no}",
                message    = f"{req.event_name} ({req.client_name or ''})",
                link       = f"/requests/{req_id}",
                ref_id     = req_id,
            )
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
        current_user.role in ("mudur", "yonetici") and
        (req.created_by == current_user.id or current_user.role == "mudur") and
        req.status in ("in_progress", "venues_contacted", "budget_ready")
    )
    if not is_edem_or_admin and not is_pm_direct:
        raise HTTPException(status_code=403, detail="Yetkisiz erişim.")

    req.status     = new_status
    req.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Post-Offer Workflow: Teklif Gönderildi / Onay / İptal / Revizyon / Tamamla
# ---------------------------------------------------------------------------

@router.post("/{req_id}/offer-sent", name="requests_offer_sent")
async def requests_offer_sent(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Teklif müşteriye gönderildi → status: offer_sent
    fetch() ile AJAX olarak da çağrılabilir (redirect'i görmez, 200/302 döner).
    """
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)
    # Onaylı bütçesi olan her non-terminal statüden offer_sent'e geçilebilir
    allowed = ("in_progress", "venues_contacted", "budget_ready", "offer_sent", "revision", "completed")
    if req.status in allowed and req.status != "offer_sent":
        req.status     = "offer_sent"
        req.updated_at = _now()
        db.commit()
    return RedirectResponse(url=f"/requests/{req_id}#tab-summary", status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/confirm", name="requests_confirm")
async def requests_confirm(
    req_id: str,
    budget_id: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Müşteri onayladı → seçilen budget 'confirmed', diğerleri değişmez, request 'confirmed'"""
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    revise_budget_id = None
    if budget_id:
        bgt = db.query(Budget).filter(Budget.id == budget_id, Budget.request_id == req_id).first()
        if bgt:
            bgt.budget_status = "confirmed"
            # Onay anı fiyat snapshot'ı
            import copy
            snap = {
                "ts":      _now().strftime("%d.%m.%Y %H:%M"),
                "label":   "Müşteri Onay Anı",
                "trigger": "confirm",
                "rows":    copy.deepcopy(bgt.rows),
            }
            snaps = bgt.price_snapshots
            snaps.append(snap)
            bgt.price_snapshots_json = json.dumps(snaps, ensure_ascii=False)
            revise_budget_id = bgt.id
        req.confirmed_budget_id = budget_id
    req.status       = "confirmed"
    req.confirmed_at = _now()
    req.updated_at   = _now()
    db.commit()
    redirect_url = f"/requests/{req_id}?show_revise={revise_budget_id}#tab-summary" if revise_budget_id else f"/requests/{req_id}#tab-summary"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/cancel-job", name="requests_cancel_job")
async def requests_cancel_job(
    req_id: str,
    reason: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """İşi iptal et → request 'cancelled', onaylı/confirmed bütçeler de cancelled"""
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req or req.status == "cancelled":
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    req.status              = "cancelled"
    req.cancellation_reason = reason.strip()
    req.updated_at          = _now()

    for b in req.budgets:
        if b.budget_status in ("approved", "confirmed", "pending_manager", "draft_manager"):
            b.budget_status = "cancelled"
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/postpone", name="requests_postpone")
async def requests_postpone(
    req_id: str,
    reason: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ertelendi → request 'postponed', aktif bütçeler olduğu gibi kalır"""
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req or req.status in ("cancelled", "completed", "postponed"):
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    req.status              = "postponed"
    req.cancellation_reason = reason.strip()
    req.updated_at          = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/revision", name="requests_revision")
async def requests_revision(
    req_id: str,
    new_check_in:       str = Form(""),
    new_check_out:      str = Form(""),
    new_accom_check_in:  str = Form(""),
    new_accom_check_out: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tarih değişikliği → request 'revision', onaylı/confirmed bütçeler draft_edem'e döner"""
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    if new_check_in:
        req.check_in  = new_check_in
        req.city      = req.city  # unchanged
    if new_check_out:
        req.check_out = new_check_out
    if new_accom_check_in:
        req.accom_check_in  = new_accom_check_in
    if new_accom_check_out:
        req.accom_check_out = new_accom_check_out

    req.status         = "revision"
    req.revision_count = (req.revision_count or 0) + 1
    req.updated_at     = _now()

    for b in req.budgets:
        if b.budget_status in ("approved", "confirmed"):
            b.budget_status = "draft_edem"
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}#tab-summary", status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/complete", name="requests_complete")
async def requests_complete(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Etkinlik tamamlandı → request 'completed'"""
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req or req.status not in ("confirmed",):
        return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)
    req.status     = "completed"
    req.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Tüm draft_edem bütçeleri manager'a gönder
# ---------------------------------------------------------------------------

@router.post("/{req_id}/send-all-to-manager", name="requests_send_all_to_manager")
async def requests_send_all_to_manager(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_edem_or_admin(current_user)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    from models import Budget as BudgetModel
    drafts = db.query(BudgetModel).filter(
        BudgetModel.request_id == req_id,
        BudgetModel.budget_status == "draft_edem",
    ).all()

    for b in drafts:
        b.budget_status = "pending_manager"

    if drafts:
        db.commit()

    # Manager bildirimi: talebi oluşturan PM'e mailto: hazırla
    manager_email = ""
    if req.created_by:
        pm = db.query(User).filter(User.id == req.created_by).first()
        if pm and pm.email:
            manager_email = pm.email

    redirect_url = f"/requests/{req_id}"
    if manager_email:
        redirect_url += f"?manager_notified={manager_email}"

    return RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_302_FOUND,
    )


# ---------------------------------------------------------------------------
# Müşteri teklif önizleme sayfası
# ---------------------------------------------------------------------------

SECTION_LABELS_TR = {
    "accommodation": "Konaklama",
    "meeting":       "Toplantı / Salon",
    "fb":            "F&B (Yiyecek & İçecek)",
    "teknik":        "Teknik Ekipman",
    "dekor":         "Dekor / Süsleme",
    "transfer":      "Transfer & Ulaşım",
    "tasarim":       "Tasarım & Basılı Malzeme",
    "other":         "Diğer Hizmetler",
}
SECTIONS_ORDER_PREVIEW = [
    "accommodation", "meeting", "fb",
    "teknik", "dekor", "transfer", "tasarim", "other",
]


def _preview_budget_data(budget, vat_mode: str = "exclusive"):
    """Bütçe satırlarını önizleme için hazırlar (sadece satış fiyatı)."""
    currency  = (budget.offer_currency or "TRY").upper()
    rate      = budget.rate_to_try(currency)
    syms      = {"TRY": "₺", "EUR": "€", "USD": "$"}
    sym       = syms.get(currency, currency)

    sections = {}
    sf_sale = sf_vat = 0.0
    grand_sale = grand_vat = 0.0

    for row in budget.rows:
        if row.get("is_accommodation_tax"):
            continue
        if row.get("is_service_fee"):
            sf_pct  = float(budget.service_fee_pct or 0)
            # hesap budget'ta tutuldu, satır değerlerinden al
            sale  = float(row.get("sale_price", 0) or 0)
            qty   = float(row.get("qty", 1) or 1)
            nts   = float(row.get("nights", 1) or 1)
            row_currency = row.get("currency", "TRY") or "TRY"
            row_rate = budget.rate_to_try(row_currency)
            conv  = (row_rate / rate) if rate else 1.0
            sf_sale += sale * qty * nts * conv
            sf_vat  += sf_sale * (float(row.get("vat_rate", 0) or 0) / 100)
            continue

        sec  = row.get("section", "other")
        qty  = float(row.get("qty", 1) or 1)
        nts  = float(row.get("nights", 1) or 1)
        sale = float(row.get("sale_price", 0) or 0)
        vat  = float(row.get("vat_rate", 0) or 0)
        row_currency = row.get("currency", "TRY") or "TRY"
        row_rate = budget.rate_to_try(row_currency)
        conv   = (row_rate / rate) if rate else 1.0
        sale_sub = sale * qty * nts * conv
        vat_sub  = sale_sub * (vat / 100)

        if sec not in sections:
            sections[sec] = {"label": SECTION_LABELS_TR.get(sec, sec), "rows": [], "subtotal": 0.0, "subtotal_vat": 0.0}
        sections[sec]["rows"].append({
            "description": row.get("description") or "",
            "unit":        row.get("unit") or "",
            "qty":         qty,
            "nights":      nts,
            "sale_price":  sale * conv,
            "vat_rate":    vat,
            "sale_total":  sale_sub,
            "vat_total":   vat_sub,
            "notes":       row.get("notes") or "",
            "is_accommodation": sec == "accommodation",
        })
        sections[sec]["subtotal"]     += sale_sub
        sections[sec]["subtotal_vat"] += vat_sub
        grand_sale += sale_sub
        grand_vat  += vat_sub

    # Sıralı section listesi
    ordered = []
    for s in SECTIONS_ORDER_PREVIEW:
        if s in sections:
            ordered.append(sections[s])
    # Özel kategoriler (sıra dışı)
    for s, v in sections.items():
        if s not in SECTIONS_ORDER_PREVIEW:
            ordered.append(v)

    sf_total = sf_sale + sf_vat
    return {
        "sections":   ordered,
        "grand_sale": grand_sale,
        "grand_vat":  grand_vat,
        "grand_total": grand_sale + grand_vat,
        "sf_sale":    sf_sale,
        "sf_vat":     sf_vat,
        "sf_total":   sf_total,
        "final_total": grand_sale + grand_vat + sf_total,
        "currency":   currency,
        "sym":        sym,
    }


@router.get("/{req_id}/preview", response_class=HTMLResponse, name="requests_preview")
async def requests_preview(
    req_id:    str,
    request:   Request,
    budget_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Müşteriye gösterilecek teklif önizleme sayfası (sidebar yok, baskıya uygun)."""
    from models import Settings as SettingsModel
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    approved_budgets = [
        b for b in req.budgets
        if b.budget_status in ("approved", "confirmed")
    ]
    if not approved_budgets:
        raise HTTPException(404, "Bu talep için onaylı bütçe bulunamadı.")

    # Seçili bütçe
    budget = next((b for b in approved_budgets if b.id == budget_id), approved_budgets[0])

    customer = (db.query(Customer).filter(Customer.id == req.customer_id).first()
                if req.customer_id else None)
    settings = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
    manager  = db.query(User).filter(User.id == req.created_by).first() if req.created_by else None

    preview_data_excl = _preview_budget_data(budget, "exclusive")
    preview_data_incl = _preview_budget_data(budget, "inclusive")

    # Müşteri template bilgisi (export butonu için)
    cust_cfg          = customer.excel_config if customer else {}
    has_cust_template = bool(
        cust_cfg.get("cell_map") and
        (getattr(customer, "excel_template_b64", "") or getattr(customer, "excel_template_path", ""))
    )
    cust_vat_mode     = cust_cfg.get("vat_mode", "exclusive")

    return templates.TemplateResponse("requests/preview.html", {
        "request":       request,
        "current_user":  current_user,
        "req":           req,
        "budget":        budget,
        "customer":      customer,
        "settings":      settings,
        "manager":       manager,
        "approved_budgets": approved_budgets,
        "data_excl":     preview_data_excl,
        "data_incl":     preview_data_incl,
        "has_cust_template": has_cust_template,
        "cust_vat_mode":     cust_vat_mode,
        "page_title":    f"Teklif Önizleme — {req.request_no}",
    })


# ---------------------------------------------------------------------------
# Hesap Dökümü — onaylı bütçe + faturalar + HBF özeti
# ---------------------------------------------------------------------------

@router.get("/{req_id}/statement", response_class=HTMLResponse, name="requests_statement")
async def requests_statement(
    req_id:    str,
    request:   Request,
    budget_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Müşteriye gönderilecek hesap dökümü: bütçe + faturalar + HBF özeti."""
    from models import Settings as SettingsModel, Invoice, ExpenseReport
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    if current_user.role not in ("admin", "mudur", "yonetici", "muhasebe_muduru"):
        raise HTTPException(403)

    # Onaylı / müşteri seçili bütçeler
    eligible = [b for b in req.budgets if b.budget_status in ("approved", "confirmed")]
    if not eligible:
        raise HTTPException(404, "Bu talep için onaylı bütçe bulunamadı.")

    # Önce confirmed varsa onu seç, yoksa approved
    confirmed_budgets = [b for b in eligible if b.budget_status == "confirmed"]
    budget = next(
        (b for b in eligible if b.id == budget_id),
        confirmed_budgets[0] if confirmed_budgets else eligible[0]
    )

    customer = (db.query(Customer).filter(Customer.id == req.customer_id).first()
                if req.customer_id else None)
    settings  = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
    manager   = db.query(User).filter(User.id == req.created_by).first() if req.created_by else None

    # Bütçe kalemleri (teklif mantığıyla aynı)
    data_excl = _preview_budget_data(budget, "exclusive")
    data_incl = _preview_budget_data(budget, "inclusive")

    # Onaylı faturalar — müşteriye kesilen (kesilen) ve iade
    approved_invoices = [i for i in req.invoices if i.status == "approved"]
    kesilen   = [i for i in approved_invoices if i.invoice_type == "kesilen"]
    iade_kesilen = [i for i in approved_invoices if i.invoice_type == "iade_kesilen"]
    total_kesilen     = sum(i.total_amount for i in kesilen)
    total_iade        = sum(i.total_amount for i in iade_kesilen)
    net_fatura_total  = round(total_kesilen - total_iade, 2)

    # Onaylı HBF'ler
    approved_hbf = [r for r in req.expense_reports if r.status == "approved"]
    total_hbf    = round(sum(r.grand_total for r in approved_hbf), 2)

    # Finansal özet
    budgeted_total = data_excl["final_total"]  # teklif edilen (KDV hariç, SF dahil)
    budgeted_incl  = data_incl["final_total"]  # teklif edilen (KDV dahil, SF dahil)

    return templates.TemplateResponse("requests/statement.html", {
        "request":         request,
        "current_user":    current_user,
        "req":             req,
        "budget":          budget,
        "eligible_budgets": eligible,
        "customer":        customer,
        "settings":        settings,
        "manager":         manager,
        "data_excl":       data_excl,
        "data_incl":       data_incl,
        "kesilen":         kesilen,
        "iade_kesilen":    iade_kesilen,
        "total_kesilen":   total_kesilen,
        "total_iade":      total_iade,
        "net_fatura_total": net_fatura_total,
        "approved_hbf":    approved_hbf,
        "total_hbf":       total_hbf,
        "budgeted_total":  budgeted_total,
        "budgeted_incl":   budgeted_incl,
        "page_title":      f"Hesap Dökümü — {req.request_no}",
    })


# ---------------------------------------------------------------------------
# Çoklu bütçe → tek Excel (özet sayfasından export)
# ---------------------------------------------------------------------------

@router.get("/{req_id}/export", name="requests_export")
async def requests_export(
    req_id:  str,
    vat:     str = "exclusive",   # ?vat=exclusive | inclusive
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Talebe bağlı tüm onaylı bütçeleri tek Excel'de birleştirir.
    Her bütçe (mekan) ayrı bir sheet olarak eklenir.
    """
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    budgets = (
        db.query(Budget)
          .filter(Budget.request_id == req_id,
                  Budget.budget_status.in_(["approved", "confirmed"]))
          .all()
    )
    if not budgets:
        raise HTTPException(404, "Bu talep için onaylı bütçe bulunamadı")

    customer = (db.query(Customer).filter(Customer.id == req.customer_id).first()
                if req.customer_id else None)

    vat_mode = vat if vat in ("exclusive", "inclusive") else "exclusive"
    custom_cats = [{"id": cc.id, "name": cc.name}
                   for cc in db.query(CustomCategory).all()]

    # Excel'de "Hazırlayan:" = talebi oluşturan PM (manager)
    manager_user = db.query(User).filter(User.id == req.created_by).first() if req.created_by else None

    entries = []
    for b in budgets:
        entries.append({
            "budget":   b,
            "request":  req,
            "customer": customer,
            "creator":  manager_user,
        })

    # ── Template & cell_map hazırlığı (HTTPException'ları try dışında) ──────────
    cfg      = customer.excel_config if customer else {}
    cell_map = cfg.get("cell_map") or {}
    b64_data = (getattr(customer, "excel_template_b64", None) or "") if customer else ""
    tpl_path = (customer.excel_template_path or "") if customer else ""

    # Dosya yoksa ama DB'de base64 varsa yeniden oluştur (Railway restart)
    if b64_data and (not tpl_path or not os.path.exists(tpl_path)):
        try:
            import base64 as _b64
            _upload_dir = "static/uploads/customer_templates"
            os.makedirs(_upload_dir, exist_ok=True)
            tpl_path = os.path.join(_upload_dir, f"{customer.id}.xlsx")
            with open(tpl_path, "wb") as _f:
                _f.write(_b64.b64decode(b64_data))
            customer.excel_template_path = tpl_path
            db.commit()
        except Exception as _e:
            print(f"[REQ-EXPORT] b64 restore hatası: {_e}", flush=True)

    has_tpl_file = bool(tpl_path and os.path.exists(tpl_path))
    use_template = bool(has_tpl_file and cell_map)

    print(
        f"[REQ-EXPORT] req={req_id} tpl_path={tpl_path!r} "
        f"has_tpl_file={has_tpl_file} b64_len={len(b64_data)} "
        f"cell_map_keys={list(cell_map.keys())} use_template={use_template}",
        flush=True,
    )

    if has_tpl_file and not cell_map:
        raise HTTPException(
            400,
            "Müşteri şablonu yüklü ama hücre eşleştirmesi yapılmamış. "
            "Müşteri sayfasından 'Şablonu Eşleştir' butonunu kullanın."
        )

    # ── Excel oluştur ────────────────────────────────────────────────────────
    try:
        if False:  # Müşteri template export geçici olarak devre dışı
            pass
        else:
            from excel_export import build_multi_sheet
            output = build_multi_sheet(entries, vat_mode=vat_mode,
                                       custom_sections=custom_cats)
    except Exception as exc:
        import traceback as _tb
        detail = f"Excel oluşturma hatası: {exc}\n{_tb.format_exc()}"
        print(detail, flush=True)
        raise HTTPException(500, detail)

    # Dosya adı
    raw_name = (req.event_name or req.request_no or "teklif")[:30]
    ascii_name = unicodedata.normalize("NFKD", raw_name)
    ascii_name = "".join(c for c in ascii_name if ord(c) < 128)
    ascii_name = ascii_name.replace(" ", "_").replace("/", "-").strip("_") or "teklif"
    filename_utf8 = urllib.parse.quote(f"{raw_name}_teklif.xlsx")
    content_disposition = (
        f'attachment; filename="{ascii_name}_teklif.xlsx"; '
        f"filename*=UTF-8''{filename_utf8}"
    )

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition},
    )


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


# ---------------------------------------------------------------------------
# Hesap Dökümü Oluştur
# ---------------------------------------------------------------------------

@router.post("/{req_id}/create-statement", name="requests_create_statement")
async def requests_create_statement(
    req_id: str,
    source_budget_id: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Onaylı bütçeden hesap dökümü kopyası oluştur → editöre yönlendir."""
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)

    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    # Mevcut statement varsa onu aç
    existing = (
        db.query(Budget)
        .filter(Budget.request_id == req_id, Budget.budget_type == "statement")
        .order_by(Budget.updated_at.desc())
        .first()
    )
    if existing:
        return RedirectResponse(url=f"/budgets/{existing.id}/statement", status_code=status.HTTP_302_FOUND)

    # Kaynak bütçeyi bul (belirtilmişse onu al, yoksa confirmed → approved sırasıyla)
    if source_budget_id:
        src = db.query(Budget).filter(Budget.id == source_budget_id, Budget.request_id == req_id).first()
    else:
        src = (
            db.query(Budget)
            .filter(Budget.request_id == req_id, Budget.budget_status == "confirmed", Budget.budget_type == "offer")
            .order_by(Budget.updated_at.desc())
            .first()
        )
        if not src:
            src = (
                db.query(Budget)
                .filter(Budget.request_id == req_id, Budget.budget_status == "approved", Budget.budget_type == "offer")
                .order_by(Budget.updated_at.desc())
                .first()
            )

    if not src:
        return RedirectResponse(url=f"/requests/{req_id}#tab-summary", status_code=status.HTTP_302_FOUND)

    # Satırlara cost_qty = qty başlangıç değeri ata (maliyet ve satış miktarı başta aynı)
    src_rows = src.rows
    for row in src_rows:
        if "cost_qty" not in row:
            row["cost_qty"] = row.get("qty", 1)
    import json as _json
    stmt_rows_json = _json.dumps(src_rows, ensure_ascii=False)

    # Yeni statement bütçesi oluştur
    stmt_budget = Budget(
        id=_uuid(),
        request_id=req_id,
        venue_name=src.venue_name,
        rows_json=stmt_rows_json,
        budget_status="confirmed",
        budget_type="statement",
        service_fee_pct=src.service_fee_pct,
        offer_currency=src.offer_currency or "TRY",
        exchange_rates_json=src.exchange_rates_json or "{}",
        created_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(stmt_budget)
    db.commit()
    db.refresh(stmt_budget)
    return RedirectResponse(url=f"/budgets/{stmt_budget.id}/statement", status_code=status.HTTP_302_FOUND)
