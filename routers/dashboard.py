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
from models import Budget, Customer, Invoice, Request as ReqModel, Service, Team, User, Venue, ClosureRequest

router = APIRouter()
from templates_config import templates


def _last_n_months(n: int = 6) -> list[str]:
    """Son n ayın YYYY-MM listesini döner (en eski → en yeni)"""
    now = datetime.utcnow()
    months = []
    for i in range(n - 1, -1, -1):
        m = now.month - i
        y = now.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        months.append(f"{y}-{m:02d}")
    return months


def _build_financial_stats(db: Session, req_id_filter=None):
    """Onaylı faturalardan ciro/kar/aylık veri hesapla — sadece gerçek rakamlar."""
    inv_query = db.query(Invoice).filter(
        Invoice.status.in_(["approved", "gm_approved", "active"]),
    )
    if req_id_filter is not None:
        inv_query = inv_query.filter(Invoice.request_id.in_(req_id_filter))

    invoices = inv_query.all()

    total_sale     = 0.0
    total_cost     = 0.0
    total_komisyon = 0.0
    monthly: dict[str, dict] = defaultdict(lambda: {"sale": 0.0, "cost": 0.0})

    for inv in invoices:
        if inv.invoice_type == "kesilen":
            total_sale += inv.amount
        elif inv.invoice_type == "iade_kesilen":
            total_sale -= inv.amount
        elif inv.invoice_type == "gelen":
            total_cost += inv.amount
        elif inv.invoice_type == "iade_gelen":
            total_cost -= inv.amount
        elif inv.invoice_type == "komisyon":
            # Komisyon faturası → gelir (kar'a direkt katkı)
            total_komisyon += inv.amount
        else:
            continue

        # Aylık gruplama: referansın etkinlik başlangıç tarihini (check_in) kullan.
        # Fatura önce ya da sonra gelse bile iş hangi ayda gerçekleştiyse o aya yaz.
        # Fallback: fatura tarihi → oluşturulma tarihi
        key = None
        req_obj = inv.request
        if req_obj and req_obj.check_in:
            try:
                ci = req_obj.check_in
                if hasattr(ci, "strftime"):
                    key = ci.strftime("%Y-%m")
                else:
                    key = str(ci)[:7]
            except Exception:
                pass
        if not key and inv.invoice_date:
            try:
                key = inv.invoice_date[:7]
            except Exception:
                pass
        if not key and inv.created_at:
            key = inv.created_at.strftime("%Y-%m")
        if key:
            if inv.invoice_type == "kesilen":
                monthly[key]["sale"] += inv.amount
            elif inv.invoice_type == "iade_kesilen":
                monthly[key]["sale"] -= inv.amount
            elif inv.invoice_type == "gelen":
                monthly[key]["cost"] += inv.amount
            elif inv.invoice_type == "iade_gelen":
                monthly[key]["cost"] -= inv.amount
            elif inv.invoice_type == "komisyon":
                monthly[key]["sale"] += inv.amount   # komisyon → gelir

    # Kar = kesilen + komisyon − gelen (requests/detail.html ile aynı formül)
    kar = total_sale + total_komisyon - total_cost
    total_revenue = total_sale + total_komisyon
    karlilik = round(kar / total_revenue * 100, 1) if total_revenue > 0 else 0.0

    labels = _last_n_months(6)
    chart_sale = [round(monthly[m]["sale"], 0) for m in labels]
    chart_cost = [round(monthly[m]["cost"], 0) for m in labels]
    chart_labels = [m[5:] + "/" + m[2:4] for m in labels]

    return {
        "total_sale":      round(total_revenue, 2),   # ciro + komisyon
        "total_cost":      round(total_cost, 2),
        "total_kar":       round(kar, 2),
        "karlilik":        karlilik,
        "chart_labels":    chart_labels,
        "chart_sale":      chart_sale,
        "chart_cost":      chart_cost,
    }


def _build_ytd_team_stats(db: Session) -> list[dict]:
    """Yılbaşından bugüne takım bazlı ciro/kar (tüm takımlar — GM/admin için)."""
    year_start = date(date.today().year, 1, 1).isoformat()

    reqs = db.query(ReqModel).filter(ReqModel.check_in >= year_start).all()
    if not reqs:
        return []
    req_team_map = {r.id: r.team_id for r in reqs}
    req_ids = list(req_team_map.keys())

    invoices = db.query(Invoice).filter(
        Invoice.status.in_(["approved", "gm_approved", "active"]),
        Invoice.request_id.in_(req_ids),
    ).all()

    team_name_map = {t.id: t.name for t in db.query(Team).all()}

    agg: dict[str, dict] = defaultdict(lambda: {"ciro": 0.0, "maliyet": 0.0, "komisyon": 0.0})
    for inv in invoices:
        tid  = req_team_map.get(inv.request_id)
        name = team_name_map.get(tid, "Takımsız") if tid else "Takımsız"
        if inv.invoice_type == "kesilen":
            agg[name]["ciro"] += inv.amount
        elif inv.invoice_type == "iade_kesilen":
            agg[name]["ciro"] -= inv.amount
        elif inv.invoice_type == "komisyon":
            agg[name]["komisyon"] += inv.amount
        elif inv.invoice_type == "gelen":
            agg[name]["maliyet"] += inv.amount
        elif inv.invoice_type == "iade_gelen":
            agg[name]["maliyet"] -= inv.amount

    rows = []
    for name, v in agg.items():
        ciro = v["ciro"] + v["komisyon"]
        kar  = ciro - v["maliyet"]
        rows.append({"name": name, "ciro": round(ciro, 0), "kar": round(kar, 0)})
    rows.sort(key=lambda r: r["ciro"], reverse=True)
    return rows


def _build_ytd_customer_stats(db: Session, req_id_filter=None, limit: int = 10) -> list[dict]:
    """Yılbaşından bugüne müşteri bazlı ciro/kar.

    req_id_filter verilirse sadece o referans ID'leri kapsanır (rol scope).
    """
    year_start = date(date.today().year, 1, 1).isoformat()

    req_q = db.query(ReqModel).filter(ReqModel.check_in >= year_start)
    if req_id_filter is not None:
        req_q = req_q.filter(ReqModel.id.in_(req_id_filter))
    reqs = req_q.all()
    if not reqs:
        return []

    req_info = {r.id: (r.customer_id, r.client_name) for r in reqs}
    cust_name_map = {c.id: c.name for c in db.query(Customer).all()}

    invoices = db.query(Invoice).filter(
        Invoice.status.in_(["approved", "gm_approved", "active"]),
        Invoice.request_id.in_(list(req_info.keys())),
    ).all()

    agg: dict[str, dict] = defaultdict(lambda: {"ciro": 0.0, "maliyet": 0.0, "komisyon": 0.0})
    for inv in invoices:
        cid, cname = req_info.get(inv.request_id, (None, None))
        key = cust_name_map.get(cid) or (cname or "—")
        if inv.invoice_type == "kesilen":
            agg[key]["ciro"] += inv.amount
        elif inv.invoice_type == "iade_kesilen":
            agg[key]["ciro"] -= inv.amount
        elif inv.invoice_type == "komisyon":
            agg[key]["komisyon"] += inv.amount
        elif inv.invoice_type == "gelen":
            agg[key]["maliyet"] += inv.amount
        elif inv.invoice_type == "iade_gelen":
            agg[key]["maliyet"] -= inv.amount

    rows = []
    for name, v in agg.items():
        ciro = v["ciro"] + v["komisyon"]
        kar  = ciro - v["maliyet"]
        if ciro == 0 and kar == 0:
            continue
        rows.append({"name": name, "ciro": round(ciro, 0), "kar": round(kar, 0)})
    rows.sort(key=lambda r: r["ciro"], reverse=True)
    return rows[:limit]


def _build_pending_tasks(db: Session, current_user) -> list[dict]:
    """Role göre bekleyen işlemleri linkli liste olarak döner."""
    tasks = []
    role = current_user.role

    # ── GM / Admin: onay bekleyen fatura talepleri ──────────────────────────
    if role in ("mudur", "admin", "muhasebe_muduru"):
        invs = (
            db.query(Invoice)
            .filter(Invoice.status == "pending")
            .order_by(Invoice.created_at.asc())
            .limit(15)
            .all()
        )
        for inv in invs:
            req = inv.request
            if not req:
                continue
            tasks.append({
                "icon": "bi-receipt",
                "color": "warning",
                "label": "Fatura Onayı",
                "text": f"{req.request_no} — {req.event_name}",
                "url": f"/requests/{req.id}",
            })

    # ── GM / Admin: kapama onayı bekleyen (pending_gm) ──────────────────────
    if role in ("mudur", "admin"):
        closures = (
            db.query(ClosureRequest)
            .filter(ClosureRequest.status == "pending_gm")
            .order_by(ClosureRequest.created_at.asc())
            .limit(10)
            .all()
        )
        for cl in closures:
            req = cl.request
            if not req:
                continue
            tasks.append({
                "icon": "bi-folder-check",
                "color": "primary",
                "label": "Kapama Onayı",
                "text": f"{req.request_no} — {req.event_name}",
                "url": f"/requests/{req.id}",
            })

    # ── Müdür: kapama onayı (pending_manager) ──────────────────────────────
    if role in ("mudur", "admin"):
        closures_mgr = (
            db.query(ClosureRequest)
            .filter(ClosureRequest.status == "pending_manager")
            .order_by(ClosureRequest.created_at.asc())
            .limit(10)
            .all()
        )
        for cl in closures_mgr:
            req = cl.request
            if not req:
                continue
            tasks.append({
                "icon": "bi-folder-check",
                "color": "warning",
                "label": "Kapama (Müdür Onayı)",
                "text": f"{req.request_no} — {req.event_name}",
                "url": f"/requests/{req.id}",
            })

    # ── Muhasebe: GM onaylı fatura kes ──────────────────────────────────────
    if role in ("muhasebe", "muhasebe_muduru", "admin"):
        invs_gm = (
            db.query(Invoice)
            .filter(Invoice.status == "gm_approved")
            .order_by(Invoice.created_at.asc())
            .limit(15)
            .all()
        )
        for inv in invs_gm:
            req = inv.request
            if not req:
                continue
            tasks.append({
                "icon": "bi-scissors",
                "color": "danger",
                "label": "Fatura Kes",
                "text": f"{req.request_no} — {req.event_name}",
                "url": f"/requests/{req.id}",
            })

    # ── Muhasebe müdürü: kapama finans onayı ───────────────────────────────
    if role in ("muhasebe_muduru", "admin"):
        closures_fin = (
            db.query(ClosureRequest)
            .filter(ClosureRequest.status == "pending_finance")
            .order_by(ClosureRequest.created_at.asc())
            .limit(10)
            .all()
        )
        for cl in closures_fin:
            req = cl.request
            if not req:
                continue
            tasks.append({
                "icon": "bi-folder-check",
                "color": "info",
                "label": "Kapama (Muhasebe Onayı)",
                "text": f"{req.request_no} — {req.event_name}",
                "url": f"/requests/{req.id}",
            })

    # ── E-dem: atanmamış talepler ──────────────────────────────────────────
    if role == "e_dem":
        pending_reqs = (
            db.query(ReqModel)
            .filter(ReqModel.status == "pending")
            .order_by(ReqModel.created_at.asc())
            .limit(15)
            .all()
        )
        for req in pending_reqs:
            tasks.append({
                "icon": "bi-inbox-fill",
                "color": "warning",
                "label": "Yeni Talep",
                "text": f"{req.request_no} — {req.event_name}",
                "url": f"/requests/{req.id}",
            })

    # ── PM / Yönetici: bütçesi hazır referanslar ─────────────────────────
    if role in ("yonetici", "asistan"):
        from routers.requests import _get_subtree_ids
        sub_ids = _get_subtree_ids(current_user.id, db)
        visible_ids = [current_user.id] + sub_ids
        budget_ready = (
            db.query(ReqModel)
            .filter(
                ReqModel.created_by.in_(visible_ids),
                ReqModel.status.in_(["budget_ready", "offer_sent"]),
            )
            .order_by(ReqModel.updated_at.desc())
            .limit(10)
            .all()
        )
        for req in budget_ready:
            tasks.append({
                "icon": "bi-calculator-fill",
                "color": "success",
                "label": "Bütçe Hazır",
                "text": f"{req.request_no} — {req.event_name}",
                "url": f"/requests/{req.id}",
            })

    return tasks


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
        # Birim müdürü: takımındaki referanslar; GM/admin/muhasebe_muduru: tümü
        if current_user.role == "mudur" and current_user.team_id and not current_user.is_gm:
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

    pending_tasks = _build_pending_tasks(db, current_user)

    # Takım YTD grafiği — GM ve admin için (tüm takımları görür)
    team_ytd = []
    show_team_ytd = current_user.is_gm or current_user.role == "admin"
    if show_team_ytd:
        team_ytd = _build_ytd_team_stats(db)

    # Müşteri YTD grafiği — finansal görüntülemesi olan roller (asistan/e_dem hariç)
    customer_ytd = []
    show_customer_ytd = current_user.role in ("admin", "mudur", "muhasebe_muduru", "yonetici")
    if show_customer_ytd:
        customer_ytd = _build_ytd_customer_stats(db, req_id_filter=req_id_filter)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request":         request,
            "current_user":    current_user,
            "stats":           stats,
            "financial":       financial,
            "recent_requests": recent_requests,
            "pending_tasks":   pending_tasks,
            "page_title":      "Dashboard",
            "chart_data":      json.dumps({
                "labels": financial.get("chart_labels", []),
                "sale":   financial.get("chart_sale", []),
                "cost":   financial.get("chart_cost", []),
            }),
            "show_team_ytd":   show_team_ytd,
            "team_ytd":        team_ytd,
            "team_ytd_json":   json.dumps({
                "labels": [t["name"] for t in team_ytd],
                "ciro":   [t["ciro"]  for t in team_ytd],
                "kar":    [t["kar"]   for t in team_ytd],
            }),
            "show_customer_ytd": show_customer_ytd,
            "customer_ytd_json": json.dumps({
                "labels": [c["name"] for c in customer_ytd],
                "ciro":   [c["ciro"]  for c in customer_ytd],
                "kar":    [c["kar"]   for c in customer_ytd],
            }),
        },
    )
