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
from models import Budget, Customer, Invoice, Request as ReqModel, User
from templates_config import templates

router = APIRouter(prefix="/reports", tags=["reports"])


FINANCE_ROLES = {"admin", "muhasebe_muduru", "muhasebe"}


def _require_admin(current_user: User):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu sayfa yalnızca Admin'e özeldir.")


def _require_finance(current_user: User):
    if current_user.role not in FINANCE_ROLES and current_user.role != "project_manager":
        raise HTTPException(status_code=403, detail="Bu sayfa için yetkiniz yok.")


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
    year:       str = "",
    manager_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)

    from collections import defaultdict

    # Yıl filtresi — varsayılan: bu yıl
    current_year = date.today().year
    selected_year = int(year) if year.isdigit() else current_year
    available_years = list(range(current_year, current_year - 5, -1))

    # Manager filtresi
    # PM: sadece kendi taleplerini görür
    # Admin / muhasebe: tüm talepler; manager_id ile filtrelenebilir
    pm_users = db.query(User).filter(User.role == "project_manager", User.active == True).all()
    if current_user.role == "project_manager":
        manager_id = current_user.id  # PM kendi ID'sini kullanır

    # Talepleri çek
    req_query = db.query(ReqModel)
    if current_user.role == "project_manager":
        req_query = req_query.filter(ReqModel.created_by == current_user.id)
    elif manager_id:
        req_query = req_query.filter(ReqModel.created_by == manager_id)

    all_reqs = req_query.all()
    req_ids = [r.id for r in all_reqs]
    req_map = {r.id: r for r in all_reqs}

    # Yıla göre filtrele: req.check_in yılı veya created_at yılı
    def _req_year(r):
        if r.check_in:
            try:
                return date.fromisoformat(r.check_in).year
            except Exception:
                pass
        return r.created_at.year if r.created_at else current_year

    filtered_req_ids = {r.id for r in all_reqs if _req_year(r) == selected_year}

    # Faturalar — approved (eski "active" de dahil geriye uyumluluk için)
    invoices = db.query(Invoice).filter(
        Invoice.request_id.in_(list(filtered_req_ids)),
        Invoice.status.in_(["approved", "active"]),
    ).all()

    # Referans bazlı finansal özet
    ref_fin = defaultdict(lambda: {
        "ciro": 0.0, "maliyet": 0.0,
        "budget_sale": 0.0, "budget_cost": 0.0,
    })
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

    # Konfirme bütçe KDV-hariç tutarlarını ekle
    all_budgets = db.query(Budget).filter(
        Budget.request_id.in_(list(filtered_req_ids)),
        Budget.budget_status == "confirmed",
    ).all()
    for b in all_budgets:
        ref_fin[b.request_id]["budget_sale"] = b.grand_sale_excl_vat
        ref_fin[b.request_id]["budget_cost"] = b.grand_cost_excl_vat

    # Tablo satırları oluştur
    rows = []
    for req in all_reqs:
        if req.id not in filtered_req_ids:
            continue
        fin = ref_fin.get(req.id, {})
        ciro     = fin.get("ciro", 0.0)
        maliyet  = fin.get("maliyet", 0.0)
        kar      = ciro - maliyet
        karlilk  = round(kar / ciro * 100, 1) if ciro > 0 else None
        rows.append({
            "req":          req,
            "manager_name": req.creator.full_name if req.creator else "—",
            "ciro":         round(ciro, 2),
            "maliyet":      round(maliyet, 2),
            "kar":          round(kar, 2),
            "karlilk":      karlilk,
            "budget_sale":  fin.get("budget_sale", 0.0),
            "budget_cost":  fin.get("budget_cost", 0.0),
        })

    rows.sort(key=lambda x: (x["req"].check_in or ""), reverse=True)

    # Genel toplamlar
    total_ciro    = sum(r["ciro"]    for r in rows)
    total_maliyet = sum(r["maliyet"] for r in rows)
    total_kar     = total_ciro - total_maliyet
    total_karlilk = round(total_kar / total_ciro * 100, 1) if total_ciro > 0 else None

    # Manager bazlı alt toplamlar (sadece admin/muhasebe için)
    mgr_totals = defaultdict(lambda: {"name": "", "ciro": 0.0, "maliyet": 0.0, "kar": 0.0})
    if current_user.role not in ("project_manager",):
        for r in rows:
            mid = r["req"].created_by or "_"
            mgr_totals[mid]["name"]    = r["manager_name"]
            mgr_totals[mid]["ciro"]    += r["ciro"]
            mgr_totals[mid]["maliyet"] += r["maliyet"]
            mgr_totals[mid]["kar"]     += r["ciro"] - r["maliyet"]

    # Seçili manager adı
    selected_manager = None
    if manager_id:
        selected_manager = db.query(User).filter(User.id == manager_id).first()

    return templates.TemplateResponse("reports/financial.html", {
        "request":          request,
        "current_user":     current_user,
        "page_title":       "Finansal Rapor",
        "rows":             rows,
        "total_ciro":       round(total_ciro, 2),
        "total_maliyet":    round(total_maliyet, 2),
        "total_kar":        round(total_kar, 2),
        "total_karlilk":    total_karlilk,
        "mgr_totals":       dict(mgr_totals),
        "selected_year":    selected_year,
        "available_years":  available_years,
        "pm_users":         pm_users,
        "selected_manager": selected_manager,
        "manager_id":       manager_id,
    })
