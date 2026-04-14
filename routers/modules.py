"""
Operasyon Ajanı Modülü — E-dem entegrasyonu.
Bir referansa Operasyon Ajanı modülünü bağlar / kaldırır.
"""
import os
import httpx
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse

from auth import get_current_user
from database import get_db
from models import Request as Req, RequestModule
from sqlalchemy.orm import Session

router = APIRouter(tags=["modules"])

OA_BASE_URL   = os.environ.get("OA_BASE_URL",  "http://localhost:8001")
OA_API_KEY    = os.environ.get("OA_API_KEY",   "oa-dev-key-change-in-production")


def _oa_headers():
    return {"X-Api-Key": OA_API_KEY, "Content-Type": "application/json"}


@router.post("/requests/{request_id}/modules/operasyon/activate")
async def activate_operasyon(
    request_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    req = db.query(Req).filter(Req.id == request_id).first()
    if not req:
        return RedirectResponse(url=f"/requests/{request_id}", status_code=303)

    # Zaten aktif mi?
    existing = db.query(RequestModule).filter(
        RequestModule.request_id == request_id,
        RequestModule.module_type == "operasyon",
        RequestModule.active == True,
    ).first()

    if existing:
        return RedirectResponse(url=f"/requests/{request_id}#operasyon-module", status_code=303)

    # Operasyon Ajanı API'sine istek at
    payload = {
        "edem_request_id":  req.id,
        "edem_request_no":  req.request_no or "",
        "event_name":       req.event_name,
        "start_date":       req.check_in.isoformat() if req.check_in else datetime.today().date().isoformat(),
        "end_date":         req.check_out.isoformat() if req.check_out else datetime.today().date().isoformat(),
        "venue":            None,
        "city":             req.cities_display or None,
    }

    # Onaylı bütçeden mekanı al
    if req.confirmed_budget_id:
        from models import Budget
        b = db.query(Budget).filter(Budget.id == req.confirmed_budget_id).first()
        if b and b.venue_name:
            payload["venue"] = b.venue_name

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{OA_BASE_URL}/api/activate",
                json=payload,
                headers=_oa_headers(),
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        # Operasyon ajanına ulaşılamıyor — hata mesajıyla geri dön
        return RedirectResponse(
            url=f"/requests/{request_id}?oa_error=1",
            status_code=303
        )

    module = RequestModule(
        request_id=request_id,
        module_type="operasyon",
        activated_by=current_user.id,
        oa_event_id=data.get("event_id"),
        oa_manager_url=data.get("manager_url"),
        oa_coordinator_url=data.get("coordinator_url"),
        oa_transfer_supplier_url=data.get("transfer_supplier_url"),
        oa_accommodation_supplier_url=data.get("accommodation_supplier_url"),
        active=True,
    )
    db.add(module)
    db.commit()

    return RedirectResponse(url=f"/requests/{request_id}#operasyon-module", status_code=303)


@router.post("/requests/{request_id}/modules/operasyon/deactivate")
async def deactivate_operasyon(
    request_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    module = db.query(RequestModule).filter(
        RequestModule.request_id == request_id,
        RequestModule.module_type == "operasyon",
        RequestModule.active == True,
    ).first()
    if module:
        module.active = False
        db.commit()
    return RedirectResponse(url=f"/requests/{request_id}#operasyon-module", status_code=303)
