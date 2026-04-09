"""
E-dem — Dashboard router
GET /dashboard → İstatistikleri sorgula, dashboard.html render et
"""

import json
from collections import defaultdict
from datetime import datetime, date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user
from database import get_db
from models import Budget, Customer, Request as ReqModel, Service, User, Venue

router = APIRouter()
from templates_config import templates


def _last_12_months() -> list[str]:
    """Son 12 ayın YYYY-MM listesini döner (en eski → en yeni)"""
    now = datetime.utcnow()
    months = []
    for i in range(11, -1, -1):
        m = now.month - i
        y = now.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        months.append(f"{y}-{m:02d}")
    return months


def _build_financial_stats(db: Session, budget_filter=None):
    """Onaylı bütçelerden ciro/kar/aylık veri hesapla.

    budget_filter: ek filtre (örn. request_id listesi)
    """
    query = db.query(Budget).filter(Budget.budget_status == "confirmed")
    if budget_filter is not None:
        query = query.filter(Budget.request_id.in_(budget_filter))

    confirmed_budgets = query.options(joinedload(Budget.request)).all()

    total_sale = 0.0
    total_cost = 0.0
    monthly: dict[str, dict] = defaultdict(lambda: {"sale": 0.0, "cost": 0.0})

    for bgt in confirmed_budgets:
        sale = bgt.grand_sale
        cost = bgt.grand_cost
        total_sale += sale
        total_cost += cost

        # Aylık gruplama: confirmed_at veya check_in tarihi
        ref_date = None
        if bgt.request:
            ref_date = bgt.request.confirmed_at or bgt.request.check_in
        if ref_date is None:
            ref_date = bgt.updated_at or bgt.created_at
        if ref_date:
            if isinstance(ref_date, date) and not isinstance(ref_date, datetime):
                key = ref_date.strftime("%Y-%m")
            else:
                key = ref_date.strftime("%Y-%m")
            monthly[key]["sale"] += sale
            monthly[key]["cost"] += cost

    kar = total_sale - total_cost
    karlilik = round(kar / total_sale * 100, 1) if total_sale > 0 else 0.0

    # Son 12 ay için sıralı veri (eksik aylar 0)
    labels = _last_12_months()
    chart_sale = [round(monthly[m]["sale"], 0) for m in labels]
    chart_cost = [round(monthly[m]["cost"], 0) for m in labels]
    chart_labels = [m[5:] + "/" + m[2:4] for m in labels]  # "04/26"

    return {
        "total_sale":  round(total_sale, 2),
        "total_cost":  round(total_cost, 2),
        "total_kar":   round(kar, 2),
        "karlilik":    karlilik,
        "chart_labels": chart_labels,
        "chart_sale":   chart_sale,
        "chart_cost":   chart_cost,
    }


@router.get("/dashboard", response_class=HTMLResponse, name="dashboard")
async def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stats = {}
    financial = {}
    recent_requests = []

    if current_user.role == "admin":
        stats = {
            "total_venues":    db.query(Venue).filter(Venue.active == True).count(),
            "total_requests":  db.query(ReqModel).count(),
            "total_users":     db.query(User).filter(User.active == True).count(),
            "total_customers": db.query(Customer).count(),
            "total_services":  db.query(Service).filter(Service.active == True).count(),
            "total_budgets":   db.query(Budget).count(),
            "open_requests":   db.query(ReqModel).filter(
                ReqModel.status.in_(["pending", "in_progress", "venues_contacted",
                                     "budget_ready", "offer_sent", "revision"])
            ).count(),
        }
        financial = _build_financial_stats(db)
        recent_requests = (
            db.query(ReqModel)
            .order_by(ReqModel.created_at.desc())
            .limit(8)
            .all()
        )

    elif current_user.role == "project_manager":
        my_req_ids = [
            r.id for r in db.query(ReqModel.id)
            .filter(ReqModel.created_by == current_user.id)
            .all()
        ]
        my_requests = db.query(ReqModel).filter(ReqModel.created_by == current_user.id)
        stats = {
            "my_total":     my_requests.count(),
            "my_draft":     my_requests.filter(ReqModel.status == "draft").count(),
            "my_pending":   db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id,
                ReqModel.status == "pending",
            ).count(),
            "budget_ready": db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id,
                ReqModel.status == "budget_ready",
            ).count(),
            "my_confirmed": db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id,
                ReqModel.status == "confirmed",
            ).count(),
            "open_requests": db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id,
                ReqModel.status.in_(["pending", "in_progress", "venues_contacted",
                                     "budget_ready", "offer_sent", "revision"])
            ).count(),
        }
        financial = _build_financial_stats(db, budget_filter=my_req_ids if my_req_ids else None)
        recent_requests = (
            db.query(ReqModel)
            .filter(ReqModel.created_by == current_user.id)
            .order_by(ReqModel.created_at.desc())
            .limit(8)
            .all()
        )

    else:  # e_dem
        my_budget_req_ids = [
            b.request_id for b in db.query(Budget.request_id)
            .filter(Budget.created_by == current_user.id)
            .distinct()
            .all()
        ]
        stats = {
            "pending":          db.query(ReqModel).filter(ReqModel.status == "pending").count(),
            "in_progress":      db.query(ReqModel).filter(ReqModel.status == "in_progress").count(),
            "venues_contacted": db.query(ReqModel).filter(ReqModel.status == "venues_contacted").count(),
            "budget_ready":     db.query(ReqModel).filter(ReqModel.status == "budget_ready").count(),
            "my_budgets":       db.query(Budget).filter(Budget.created_by == current_user.id).count(),
            "open_requests":    db.query(ReqModel).filter(
                ReqModel.status.in_(["pending", "in_progress", "venues_contacted", "budget_ready"])
            ).count(),
        }
        financial = _build_financial_stats(db, budget_filter=my_budget_req_ids if my_budget_req_ids else None)
        recent_requests = (
            db.query(ReqModel)
            .filter(ReqModel.status.in_(["pending", "in_progress", "venues_contacted"]))
            .order_by(ReqModel.created_at.desc())
            .limit(8)
            .all()
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request":         request,
            "current_user":    current_user,
            "stats":           stats,
            "financial":       financial,
            "recent_requests": recent_requests,
            "page_title":      "Dashboard",
            "chart_data":      json.dumps({
                "labels": financial.get("chart_labels", []),
                "sale":   financial.get("chart_sale", []),
                "cost":   financial.get("chart_cost", []),
            }),
        },
    )
