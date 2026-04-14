from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from database import init_db
import templates_config  # filtreler burada kayıtlı, import yeterli
from routers import events, participants, flights, accommodations, transfers, imports, checkin, agenda, access, api


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Operasyon Ajanı", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Router'lar
app.include_router(events.router)
app.include_router(participants.router)
app.include_router(flights.router)
app.include_router(accommodations.router)
app.include_router(transfers.router)
app.include_router(imports.router)
app.include_router(checkin.router)
app.include_router(agenda.router)
app.include_router(access.router)
app.include_router(api.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/events")
