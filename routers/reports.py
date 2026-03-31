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
from models import Budget, Customer, Request as ReqModel, User
from templates_config import templates

router = APIRouter(prefix="/reports", tags=["reports"])


def _require_admin(current_user: User):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu sayfa yalnızca Admin'e özeldir.")


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
