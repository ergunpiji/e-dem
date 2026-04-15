"""
Müşteri / Katılımcı Portalı — Salt-okunur etkinlik görünümü.
/client/{token}  →  etkinlik özeti + program + katılımcı istatistikleri
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime
from collections import OrderedDict

from database import get_db
from models import Event, UserToken, Participant, AgendaSession, SESSION_TYPES
from templates_config import templates

router = APIRouter(tags=["client"])


@router.get("/client/{token}", response_class=HTMLResponse)
async def client_portal(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
):
    """Müşteri/Katılımcı salt-okunur portalı. Token ile erişilir, login gerekmez."""
    ut = db.query(UserToken).filter(
        UserToken.token == token,
        UserToken.role == "client",
        UserToken.active == True,
    ).first()

    if not ut:
        return HTMLResponse("""
        <html><body style='font-family:sans-serif;text-align:center;padding:60px'>
        <h2>❌ Geçersiz veya süresi dolmuş bağlantı</h2>
        <p>Bu link artık aktif değil. Proje yöneticinizden yeni bir link isteyin.</p>
        </body></html>
        """, status_code=404)

    # Son kullanım zamanını güncelle
    ut.last_used_at = datetime.utcnow()
    db.commit()

    event = db.query(Event).filter(Event.id == ut.event_id).first()
    if not event:
        return HTMLResponse("<h2>Etkinlik bulunamadı.</h2>", status_code=404)

    # Program — güne göre grupla
    sessions = (
        db.query(AgendaSession)
        .filter(AgendaSession.event_id == event.id)
        .order_by(AgendaSession.session_date, AgendaSession.start_time, AgendaSession.sort_order)
        .all()
    )
    by_day: dict = OrderedDict()
    for s in sessions:
        key = s.session_date
        if key not in by_day:
            by_day[key] = []
        by_day[key].append(s)

    # Katılımcı istatistikleri (isimler gösterilmez, sadece sayılar)
    participants = db.query(Participant).filter(Participant.event_id == event.id).all()
    participant_count = len(participants)
    complete_count = sum(1 for p in participants if p.status == "complete")
    warning_count  = sum(1 for p in participants if p.status == "warning")

    return templates.TemplateResponse("client/overview.html", {
        "request":          request,
        "event":            event,
        "by_day":           by_day,
        "session_types":    SESSION_TYPES,
        "participant_count": participant_count,
        "complete_count":   complete_count,
        "warning_count":    warning_count,
        "token":            token,
    })
