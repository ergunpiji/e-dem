from fastapi import APIRouter, Depends, Request, File, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from templates_config import templates
from sqlalchemy.orm import Session
from datetime import date
import json

from database import get_db
from models import Event, Participant, FlightRecord, AccommodationRecord, TransferRecord
from services.excel_parser import parse_participant_excel


def to_date(val) -> date | None:
    """String veya None → Python date objesi."""
    if not val:
        return None
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val)[:10])
    except (ValueError, TypeError):
        return None

router = APIRouter(prefix="/events/{event_id}/import", tags=["imports"])


@router.get("/", response_class=HTMLResponse)
async def import_form(request: Request, event_id: str, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url="/events")
    return templates.TemplateResponse("imports/upload.html", {
        "request": request,
        "event": event,
        "active": "import"
    })


@router.post("/upload")
async def upload_excel(
    request: Request,
    event_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url="/events")

    content = await file.read()

    try:
        parsed = await parse_participant_excel(content, file.filename or "")
        return templates.TemplateResponse("imports/preview.html", {
            "request": request,
            "event": event,
            "parsed": parsed,
            "parsed_json": json.dumps(parsed, ensure_ascii=False, default=str),
            "filename": file.filename,
            "active": "import"
        })
    except Exception as e:
        return templates.TemplateResponse("imports/upload.html", {
            "request": request,
            "event": event,
            "error": str(e),
            "active": "import"
        })


@router.post("/confirm")
async def confirm_import(
    request: Request,
    event_id: str,
    parsed_json: str = Form(...),
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url="/events")

    data = json.loads(parsed_json)
    imported = 0
    skipped = 0

    # İsim bazlı tekilleştir — aynı ad+soyaddan birden fazla varsa ilkini al
    seen: set[str] = set()
    unique_data = []
    for row in data:
        key = f"{row.get('first_name','').strip().lower()}|{row.get('last_name','').strip().lower()}"
        if key in seen or not row.get("first_name"):
            skipped += 1
            continue
        seen.add(key)
        unique_data.append(row)
    data = unique_data

    # Etkinlikte zaten olan katılımcıları atla
    existing = db.query(Participant).filter(Participant.event_id == event_id).all()
    existing_keys = {f"{p.first_name.strip().lower()}|{p.last_name.strip().lower()}" for p in existing}

    for row in data:
        key = f"{row.get('first_name','').strip().lower()}|{row.get('last_name','').strip().lower()}"
        if key in existing_keys:
            skipped += 1
            continue

        p = Participant(
            event_id=event_id,
            first_name=row.get("first_name", ""),
            last_name=row.get("last_name", ""),
            company=row.get("company"),
            title=row.get("title"),
            email=row.get("email"),
            phone=row.get("phone"),
            badge_name=row.get("badge_name"),
            dietary=row.get("dietary"),
            special_needs=row.get("special_needs"),
            notes=row.get("notes"),
        )
        db.add(p)
        db.flush()  # id'yi al

        # Geliş uçuşu
        fi = row.get("flight_in")
        if fi:
            flight = FlightRecord(
                participant_id=p.id,
                direction="in",
                flight_number=fi.get("flight_number"),
                airline=fi.get("airline"),
                departure_airport=fi.get("departure_airport"),
                arrival_airport=fi.get("arrival_airport"),
                flight_date=to_date(fi.get("flight_date")),
                departure_time=fi.get("departure_time"),
                arrival_time=fi.get("arrival_time"),
                seat=fi.get("seat"),
                pnr=fi.get("pnr"),
            )
            db.add(flight)

        # Dönüş uçuşu
        fo = row.get("flight_out")
        if fo:
            flight = FlightRecord(
                participant_id=p.id,
                direction="out",
                flight_number=fo.get("flight_number"),
                airline=fo.get("airline"),
                departure_airport=fo.get("departure_airport"),
                arrival_airport=fo.get("arrival_airport"),
                flight_date=to_date(fo.get("flight_date")),
                departure_time=fo.get("departure_time"),
                arrival_time=fo.get("arrival_time"),
                seat=fo.get("seat"),
                pnr=fo.get("pnr"),
            )
            db.add(flight)

        # Konaklama
        acc = row.get("accommodation")
        if acc:
            accommodation = AccommodationRecord(
                participant_id=p.id,
                hotel=acc.get("hotel"),
                room_number=acc.get("room_number"),
                room_type=acc.get("room_type"),
                check_in=to_date(acc.get("check_in")),
                check_out=to_date(acc.get("check_out")),
                notes=acc.get("notes"),
            )
            db.add(accommodation)

        imported += 1

    db.commit()

    return RedirectResponse(
        url=f"/events/{event_id}/participants?imported={imported}&skipped={skipped}",
        status_code=303
    )
