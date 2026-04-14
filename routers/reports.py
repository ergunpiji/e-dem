"""
E-dem — Raporlar (Admin only)
GET /reports  → özet istatistikler, aylık trend, müşteri bazlı tablo
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Budget, Customer, Invoice, Request as ReqModel, Team, User
from templates_config import templates

router = APIRouter(prefix="/reports", tags=["reports"])


FINANCE_ROLES = {"admin", "muhasebe_muduru", "muhasebe"}


def _require_admin(current_user: User):
    """Admin veya GM (takımsız mudur) erişebilir."""
    if current_user.role == "admin":
        return
    if current_user.role == "mudur" and not current_user.team_id:
        return
    raise HTTPException(status_code=403, detail="Bu sayfa yalnızca Admin ve Genel Müdür'e özeldir.")


def _require_finance(current_user: User):
    if current_user.role not in FINANCE_ROLES and current_user.role not in ("mudur", "yonetici", "asistan"):
        raise HTTPException(status_code=403, detail="Bu sayfa için yetkiniz yok.")


def _is_gm(user: User) -> bool:
    """Genel Müdür mü? → mudur rolü + takımsız VEYA admin."""
    if user.role == "admin":
        return True
    if user.role == "mudur" and not user.team_id:
        return True
    return False


@router.get("", response_class=HTMLResponse, name="reports")
async def reports(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)

    today = date.today()
    month_start = today.replace(day=1)

    # ── Özet kartlar ──
    total_requests   = db.query(ReqModel).count()
    this_month_reqs  = db.query(ReqModel).filter(
        ReqModel.created_at >= datetime.combine(month_start, datetime.min.time())
    ).count()
    budget_ready     = db.query(ReqModel).filter(ReqModel.status == "budget_ready").count()
    completed        = db.query(ReqModel).filter(ReqModel.status == "completed").count()
    total_budgets    = db.query(Budget).count()
    total_customers  = db.query(Customer).count()

    # ── Durum dağılımı ──
    status_rows = db.query(ReqModel.status, func.count(ReqModel.id))\
        .group_by(ReqModel.status).all()
    status_dist = {row[0]: row[1] for row in status_rows}

    # ── Son 6 ayın aylık talep sayısı ──
    monthly = []
    for i in range(5, -1, -1):
        # i ay öncesinin ilk günü
        d = (today.replace(day=1) - timedelta(days=1)).replace(day=1) if i > 0 else today.replace(day=1)
        # Basit yol: ay = today.month - i, yıl ayarla
        month_num = today.month - i
        year_num  = today.year
        while month_num <= 0:
            month_num += 12
            year_num  -= 1
        m_start = datetime(year_num, month_num, 1)
        if month_num == 12:
            m_end = datetime(year_num + 1, 1, 1)
        else:
            m_end = datetime(year_num, month_num + 1, 1)
        cnt = db.query(ReqModel).filter(
            ReqModel.created_at >= m_start,
            ReqModel.created_at < m_end,
        ).count()
        monthly.append({
            "label": m_start.strftime("%b %Y"),
            "count": cnt,
        })

    # ── Müşteri bazlı tablo ──
    all_reqs = db.query(ReqModel).all()
    all_budgets = db.query(Budget).all()

    budget_by_req = defaultdict(list)
    for b in all_budgets:
        budget_by_req[b.request_id].append(b)

    customer_stats = defaultdict(lambda: {
        "name": "", "req_count": 0, "budget_count": 0,
        "total_cost": 0.0, "total_sale": 0.0
    })

    for req in all_reqs:
        key = req.customer_id or "_no_customer"
        if req.customer:
            customer_stats[key]["name"] = req.customer.name
        else:
            customer_stats[key]["name"] = req.client_name or "—"
        customer_stats[key]["req_count"] += 1
        for b in budget_by_req.get(req.id, []):
            customer_stats[key]["budget_count"] += 1
            customer_stats[key]["total_cost"] += b.grand_cost
            customer_stats[key]["total_sale"] += b.grand_sale

    customer_table = sorted(
        customer_stats.values(),
        key=lambda x: x["req_count"],
        reverse=True,
    )

    # ── Bütçe özeti (yalnızca tamamlanan talepler) ──
    completed_req_ids = {
        r.id for r in db.query(ReqModel).filter(ReqModel.status == "completed").all()
    }
    completed_budgets = [b for b in all_budgets if b.request_id in completed_req_ids]
    total_cost = sum(b.grand_cost for b in completed_budgets)
    total_sale = sum(b.grand_sale for b in completed_budgets)

    # ── Potansiyel iş hacmi (iptal/taslak/tamamlanan dışı, bütçesi hazırlanmış) ──
    PIPELINE_STATUSES = {"in_progress", "venues_contacted", "budget_ready"}
    pipeline_req_ids = {
        r.id for r in db.query(ReqModel).filter(ReqModel.status.in_(PIPELINE_STATUSES)).all()
    }
    pipeline_budgets = [b for b in all_budgets if b.request_id in pipeline_req_ids]
    pipeline_cost = sum(b.grand_cost for b in pipeline_budgets)
    pipeline_sale = sum(b.grand_sale for b in pipeline_budgets)
    pipeline_count = len({b.request_id for b in pipeline_budgets})

    return templates.TemplateResponse("reports/index.html", {
        "request":        request,
        "current_user":   current_user,
        "page_title":     "Raporlar",
        # Özet
        "total_requests":  total_requests,
        "this_month_reqs": this_month_reqs,
        "budget_ready":    budget_ready,
        "completed":       completed,
        "total_budgets":   total_budgets,
        "total_customers": total_customers,
        # Durum dağılımı
        "status_dist":     status_dist,
        # Aylık trend
        "monthly":         monthly,
        # Müşteri tablosu
        "customer_table":  customer_table,
        # Bütçe özeti
        "total_cost":      total_cost,
        "total_sale":      total_sale,
        # Potansiyel iş hacmi
        "pipeline_cost":   pipeline_cost,
        "pipeline_sale":   pipeline_sale,
        "pipeline_count":  pipeline_count,
    })


# ---------------------------------------------------------------------------
# Finansal Rapor
# ---------------------------------------------------------------------------

@router.get("/financial", response_class=HTMLResponse, name="reports_financial")
async def reports_financial(
    request: Request,
    date_from:  str = "",
    date_to:    str = "",
    manager_id: str = "",
    team_id:    str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)

    import json as _json
    from collections import defaultdict

    today = date.today()

    # Tarih aralığı — varsayılan: bu yılın başı → bugün
    try:
        d_from = date.fromisoformat(date_from) if date_from else today.replace(month=1, day=1)
    except ValueError:
        d_from = today.replace(month=1, day=1)
    try:
        d_to = date.fromisoformat(date_to) if date_to else today
    except ValueError:
        d_to = today

    is_gm_user   = _is_gm(current_user)
    is_birim_mgr = (current_user.role == "mudur" and not is_gm_user)

    # PM/yönetici: sadece kendi
    if current_user.role in ("yonetici", "asistan"):
        manager_id = current_user.id

    # Birim müdürü: sadece kendi takımının üyeleri
    scoped_user_ids: list[str] | None = None
    if is_birim_mgr and current_user.team_id:
        team_members = db.query(User).filter(
            User.team_id == current_user.team_id, User.active == True
        ).all()
        scoped_user_ids = [u.id for u in team_members]
        team_id = current_user.team_id  # filtre override

    # Takım listesi (GM için filtre dropdown)
    all_teams = db.query(Team).filter(Team.active == True).order_by(Team.name).all() if is_gm_user else []

    # GM takım filtresi
    if is_gm_user and team_id:
        team_members_gm = db.query(User).filter(
            User.team_id == team_id, User.active == True
        ).all()
        scoped_user_ids = [u.id for u in team_members_gm]

    # PM filtresi (sadece GM/admin/muhasebe için)
    pm_users = []
    if current_user.role not in ("yonetici", "asistan", "mudur"):
        pm_users = db.query(User).filter(
            User.role.in_(["mudur", "yonetici", "asistan"]), User.active == True
        ).all()

    # Fatura bazlı sorgulama: taleplerin etkinlik başlangıç tarihi (check_in) aralığa göre filtrele.
    # Gruplama ile tutarlı olması için fatura tarihi değil iş tarihi esas alınır.
    req_date_q = db.query(ReqModel.id).filter(
        ReqModel.check_in >= d_from.isoformat(),
        ReqModel.check_in <= d_to.isoformat(),
    )

    if scoped_user_ids is not None:
        req_date_q = req_date_q.filter(ReqModel.created_by.in_(scoped_user_ids))
    elif current_user.role in ("yonetici", "asistan"):
        req_date_q = req_date_q.filter(ReqModel.created_by == current_user.id)
    elif manager_id:
        req_date_q = req_date_q.filter(ReqModel.created_by == manager_id)

    in_range_req_ids = [r.id for r in req_date_q.all()]

    inv_query = db.query(Invoice).filter(
        Invoice.status.in_(["approved", "active"]),
        Invoice.request_id.in_(in_range_req_ids),
    )

    invoices = inv_query.all()

    # Referans bazlı finansal özet
    ref_fin: dict = defaultdict(lambda: {"ciro": 0.0, "maliyet": 0.0})
    for inv in invoices:
        rid = inv.request_id
        if inv.invoice_type == "kesilen":
            ref_fin[rid]["ciro"] += inv.amount
        elif inv.invoice_type == "iade_kesilen":
            ref_fin[rid]["ciro"] -= inv.amount
        elif inv.invoice_type in ("gelen", "komisyon"):
            ref_fin[rid]["maliyet"] += inv.amount
        elif inv.invoice_type == "iade_gelen":
            ref_fin[rid]["maliyet"] -= inv.amount

    # İlgili talepleri toplu çek
    req_ids_with_inv = list(ref_fin.keys())
    reqs = {r.id: r for r in db.query(ReqModel)
            .filter(ReqModel.id.in_(req_ids_with_inv)).all()} if req_ids_with_inv else {}

    # Kullanıcı → takım haritası (GM için takım breakdown)
    user_team_map: dict[str, str] = {}  # user_id → team_name
    if is_gm_user:
        all_users_in_teams = db.query(User).filter(User.team_id.isnot(None)).all()
        team_name_map = {t.id: t.name for t in db.query(Team).all()}
        for u in all_users_in_teams:
            user_team_map[u.id] = team_name_map.get(u.team_id, "Takımsız")

    # Tablo satırları
    rows = []
    for rid, fin in ref_fin.items():
        req = reqs.get(rid)
        if not req:
            continue
        ciro    = round(fin["ciro"], 2)
        maliyet = round(fin["maliyet"], 2)
        kar     = round(ciro - maliyet, 2)
        team_name = user_team_map.get(req.created_by, "Takımsız") if is_gm_user else ""
        rows.append({
            "req":          req,
            "manager_name": req.creator.full_name if req.creator else "—",
            "customer":     req.client_name or "—",
            "ciro":         ciro,
            "maliyet":      maliyet,
            "kar":          kar,
            "karlilk":      round(kar / ciro * 100, 1) if ciro > 0 else None,
            "team_name":    team_name,
        })

    rows.sort(key=lambda x: (x["req"].check_in or ""), reverse=True)

    # Genel toplamlar
    total_ciro    = round(sum(r["ciro"]    for r in rows), 2)
    total_maliyet = round(sum(r["maliyet"] for r in rows), 2)
    total_kar     = round(total_ciro - total_maliyet, 2)
    total_karlilk = round(total_kar / total_ciro * 100, 1) if total_ciro > 0 else None

    # Müşteri bazlı özet (bar chart için)
    cust_map: dict = defaultdict(lambda: {"ciro": 0.0, "maliyet": 0.0, "kar": 0.0})
    for r in rows:
        k = r["customer"]
        cust_map[k]["ciro"]    += r["ciro"]
        cust_map[k]["maliyet"] += r["maliyet"]
        cust_map[k]["kar"]     += r["kar"]
    cust_list = sorted(cust_map.items(), key=lambda x: x[1]["ciro"], reverse=True)[:15]

    # Aylık trend — referansın etkinlik başlangıç tarihine (check_in) göre grupla.
    # Fatura tarihi değil, işin gerçekleştiği ay esas alınır.
    monthly: dict = defaultdict(lambda: {"ciro": 0.0, "maliyet": 0.0})
    for inv in invoices:
        req_r = reqs.get(inv.request_id)
        ym = None
        if req_r and req_r.check_in:
            try:
                ci = req_r.check_in
                ym = ci.strftime("%Y-%m") if hasattr(ci, "strftime") else str(ci)[:7]
            except Exception:
                pass
        if not ym and inv.invoice_date:
            try:
                ym = inv.invoice_date[:7]
            except Exception:
                pass
        if not ym:
            continue
        if inv.invoice_type == "kesilen":
            monthly[ym]["ciro"] += inv.amount
        elif inv.invoice_type == "iade_kesilen":
            monthly[ym]["ciro"] -= inv.amount
        elif inv.invoice_type in ("gelen", "komisyon"):
            monthly[ym]["maliyet"] += inv.amount
        elif inv.invoice_type == "iade_gelen":
            monthly[ym]["maliyet"] -= inv.amount

    sorted_months = sorted(monthly.keys())
    monthly_labels  = [f"{m[5:]}/{m[2:4]}" for m in sorted_months]
    monthly_ciro    = [round(monthly[m]["ciro"], 0) for m in sorted_months]
    monthly_maliyet = [round(monthly[m]["maliyet"], 0) for m in sorted_months]
    monthly_kar     = [round(monthly[m]["ciro"] - monthly[m]["maliyet"], 0) for m in sorted_months]

    # ── TAKIM BAZLI BREAKDOWN (GM için) ──────────────────────────────────────
    team_totals: dict = defaultdict(lambda: {"name": "", "ciro": 0.0, "maliyet": 0.0, "kar": 0.0})
    if is_gm_user:
        for r in rows:
            tname = r["team_name"] or "Takımsız"
            team_totals[tname]["name"]    = tname
            team_totals[tname]["ciro"]    += r["ciro"]
            team_totals[tname]["maliyet"] += r["maliyet"]
            team_totals[tname]["kar"]     += r["kar"]

    # ── ÜYE BAZLI PERFORMANS (Birim Müdürü için) ─────────────────────────────
    member_totals: dict = defaultdict(lambda: {"name": "", "ciro": 0.0, "maliyet": 0.0, "kar": 0.0, "count": 0})
    if is_birim_mgr:
        for r in rows:
            mid = r["req"].created_by or "_"
            member_totals[mid]["name"]    = r["manager_name"]
            member_totals[mid]["ciro"]    += r["ciro"]
            member_totals[mid]["maliyet"] += r["maliyet"]
            member_totals[mid]["kar"]     += r["kar"]
            member_totals[mid]["count"]   += 1

    # ── ESKI PM BAZLI ÖZET (admin/muhasebe için) ──────────────────────────────
    mgr_totals: dict = defaultdict(lambda: {"name": "", "ciro": 0.0, "maliyet": 0.0, "kar": 0.0})
    if current_user.role not in ("yonetici", "asistan", "mudur"):
        for r in rows:
            mid = r["req"].created_by or "_"
            mgr_totals[mid]["name"]    = r["manager_name"]
            mgr_totals[mid]["ciro"]    += r["ciro"]
            mgr_totals[mid]["maliyet"] += r["maliyet"]
            mgr_totals[mid]["kar"]     += r["kar"]

    return templates.TemplateResponse("reports/financial.html", {
        "request":        request,
        "current_user":   current_user,
        "page_title":     "Finansal Rapor",
        "is_gm":          is_gm_user,
        "is_birim_mgr":   is_birim_mgr,
        "rows":           rows,
        "total_ciro":     total_ciro,
        "total_maliyet":  total_maliyet,
        "total_kar":      total_kar,
        "total_karlilk":  total_karlilk,
        "mgr_totals":     dict(mgr_totals),
        "team_totals":    dict(team_totals),
        "member_totals":  dict(member_totals),
        "pm_users":       pm_users,
        "all_teams":      all_teams,
        "manager_id":     manager_id,
        "team_id":        team_id,
        "date_from":      d_from.isoformat(),
        "date_to":        d_to.isoformat(),
        "chart_monthly":  _json.dumps({
            "labels":   monthly_labels,
            "ciro":     monthly_ciro,
            "maliyet":  monthly_maliyet,
            "kar":      monthly_kar,
        }),
        "chart_customer": _json.dumps({
            "labels":   [c[0] for c in cust_list],
            "ciro":     [round(c[1]["ciro"], 0) for c in cust_list],
            "kar":      [round(c[1]["kar"], 0) for c in cust_list],
        }),
    })
