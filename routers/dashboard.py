"""
E-dem — Dashboard router
GET /dashboard → İstatistikleri sorgula, dashboard.html render et
"""

import json
from collections import defaultdict
from datetime import datetime, date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Budget, Customer, Invoice, Request as ReqModel, Service, User, Venue

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


def _build_financial_stats(db: Session, req_id_filter=None):
    """Onaylı faturalardan ciro/kar/aylık veri hesapla — sadece gerçek rakamlar."""
    inv_query = db.query(Invoice).filter(
        Invoice.status.in_(["approved", "active"]),
    )
    if req_id_filter is not None:
        inv_query = inv_query.filter(Invoice.request_id.in_(req_id_filter))

    invoices = inv_query.all()

    total_sale = 0.0
    total_cost = 0.0
    monthly: dict[str, dict] = defaultdict(lambda: {"sale": 0.0, "cost": 0.0})

    for inv in invoices:
        if inv.invoice_type == "kesilen":
            total_sale += inv.amount
        elif inv.invoice_type == "iade_kesilen":
            total_sale -= inv.amount
        elif inv.invoice_type in ("gelen", "komisyon"):
            total_cost += inv.amount
        elif inv.invoice_type == "iade_gelen":
            total_cost -= inv.amount
        else:
            continue

        # Aylık gruplama: invoice_date → fatura tarihi kullan
        key = None
        if inv.invoice_date:
            try:
                key = inv.invoice_date[:7]  # YYYY-MM
            except Exception:
                pass
        if not key and inv.created_at:
            key = inv.created_at.strftime("%Y-%m")
        if key:
            if inv.invoice_type == "kesilen":
                monthly[key]["sale"] += inv.amount
            elif inv.invoice_type == "iade_kesilen":
                monthly[key]["sale"] -= inv.amount
            elif inv.invoice_type in ("gelen", "komisyon"):
                monthly[key]["cost"] += inv.amount
            elif inv.invoice_type == "iade_gelen":
                monthly[key]["cost"] -= inv.amount

    kar = total_sale - total_cost
    karlilik = round(kar / total_sale * 100, 1) if total_sale > 0 else 0.0

    labels = _last_12_months()
    chart_sale = [round(monthly[m]["sale"], 0) for m in labels]
    chart_cost = [round(monthly[m]["cost"], 0) for m in labels]
    chart_labels = [m[5:] + "/" + m[2:4] for m in labels]

    return {
        "total_sale":   round(total_sale, 2),
        "total_cost":   round(total_cost, 2),
        "total_kar":    round(kar, 2),
        "karlilik":     karlilik,
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

    if current_user.role in ("admin", "mudur", "muhasebe_muduru"):
        # Müdür: takımındaki referanslar; takımsız veya admin/muhasebe_muduru: tümü
        if current_user.role == "mudur" and current_user.team_id:
            team_ids = [u.id for u in db.query(User).filter(
                User.team_id == current_user.team_id, User.active == True).all()]
            req_filter = ReqModel.created_by.in_(team_ids + [current_user.id])
            req_id_filter = [r.id for r in db.query(ReqModel.id).filter(req_filter).all()]
            base_q = db.query(ReqModel).filter(req_filter)
        else:
            req_id_filter = None
            base_q = db.query(ReqModel)

        stats = {
            "total_venues":    db.query(Venue).filter(Venue.active == True).count(),
            "total_requests":  base_q.count(),
            "total_users":     db.query(User).filter(User.active == True).count(),
            "total_customers": db.query(Customer).count(),
            "total_budgets":   db.query(Budget).count(),
            "open_requests":   base_q.filter(
                ReqModel.status.in_(["pending", "in_progress", "venues_contacted",
                                     "budget_ready", "offer_sent", "revision"])
            ).count(),
        }
        financial = _build_financial_stats(db, req_id_filter=req_id_filter)
        recent_requests = (
            base_q.order_by(ReqModel.created_at.desc()).limit(8).all()
        )

    elif current_user.role == "yonetici":
        from routers.requests import _get_subtree_ids
        sub_ids = _get_subtree_ids(current_user.id, db)
        visible_ids = [current_user.id] + sub_ids
        base_q = db.query(ReqModel).filter(ReqModel.created_by.in_(visible_ids))
        req_id_filter = [r.id for r in db.query(ReqModel.id).filter(
            ReqModel.created_by.in_(visible_ids)).all()]
        stats = {
            "my_total":     base_q.count(),
            "my_draft":     base_q.filter(ReqModel.status == "draft").count(),
            "my_pending":   db.query(ReqModel).filter(
                ReqModel.created_by.in_(visible_ids), ReqModel.status == "pending").count(),
            "budget_ready": db.query(ReqModel).filter(
                ReqModel.created_by.in_(visible_ids), ReqModel.status == "budget_ready").count(),
            "my_confirmed": db.query(ReqModel).filter(
                ReqModel.created_by.in_(visible_ids), ReqModel.status == "confirmed").count(),
            "open_requests": db.query(ReqModel).filter(
                ReqModel.created_by.in_(visible_ids),
                ReqModel.status.in_(["pending", "in_progress", "venues_contacted",
                                     "budget_ready", "offer_sent", "revision"])
            ).count(),
        }
        financial = _build_financial_stats(db, req_id_filter=req_id_filter)
        recent_requests = (
            base_q.order_by(ReqModel.created_at.desc()).limit(8).all()
        )

    elif current_user.role == "asistan":
        # Asistan: sadece kendi referanslarının sayısal istatistikleri — finansal veri yok
        my_q = db.query(ReqModel).filter(ReqModel.created_by == current_user.id)
        stats = {
            "my_total":     my_q.count(),
            "my_draft":     db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id, ReqModel.status == "draft").count(),
            "my_pending":   db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id, ReqModel.status == "pending").count(),
            "budget_ready": db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id, ReqModel.status == "budget_ready").count(),
            "my_confirmed": db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id, ReqModel.status == "confirmed").count(),
            "open_requests": db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id,
                ReqModel.status.in_(["pending", "in_progress", "venues_contacted",
                                     "budget_ready", "offer_sent", "revision"])
            ).count(),
        }
        financial = {}   # asistan finansal veri görmez
        recent_requests = (
            my_q.order_by(ReqModel.created_at.desc()).limit(8).all()
        )

    else:  # e_dem, muhasebe — sadece iş yükü, finansal bilgi yok
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
        financial = {}
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
