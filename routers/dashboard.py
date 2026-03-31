"""
E-dem — Dashboard router
GET /dashboard → İstatistikleri sorgula, dashboard.html render et
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Budget, Customer, Request as ReqModel, Service, User, Venue

router = APIRouter()
from templates_config import templates


@router.get("/dashboard", response_class=HTMLResponse, name="dashboard")
async def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stats = {}

    if current_user.role == "admin":
        stats = {
            "total_venues":    db.query(Venue).filter(Venue.active == True).count(),
            "total_requests":  db.query(ReqModel).count(),
            "total_users":     db.query(User).filter(User.active == True).count(),
            "total_customers": db.query(Customer).count(),
            "total_services":  db.query(Service).filter(Service.active == True).count(),
            "total_budgets":   db.query(Budget).count(),
        }
        recent_requests = (
            db.query(ReqModel)
            .order_by(ReqModel.created_at.desc())
            .limit(5)
            .all()
        )

    elif current_user.role == "project_manager":
        my_requests = db.query(ReqModel).filter(
            ReqModel.created_by == current_user.id
        )
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
        }
        recent_requests = (
            db.query(ReqModel)
            .filter(ReqModel.created_by == current_user.id)
            .order_by(ReqModel.created_at.desc())
            .limit(5)
            .all()
        )

    else:  # e_dem
        stats = {
            "pending":          db.query(ReqModel).filter(ReqModel.status == "pending").count(),
            "in_progress":      db.query(ReqModel).filter(ReqModel.status == "in_progress").count(),
            "venues_contacted": db.query(ReqModel).filter(ReqModel.status == "venues_contacted").count(),
            "budget_ready":     db.query(ReqModel).filter(ReqModel.status == "budget_ready").count(),
            "my_budgets":       db.query(Budget).filter(Budget.created_by == current_user.id).count(),
        }
        recent_requests = (
            db.query(ReqModel)
            .filter(ReqModel.status.in_(["pending", "in_progress", "venues_contacted"]))
            .order_by(ReqModel.created_at.desc())
            .limit(5)
            .all()
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request":        request,
            "current_user":   current_user,
            "stats":          stats,
            "recent_requests": recent_requests,
            "page_title":     "Dashboard",
        },
    )
