"""
E-dem — Ana FastAPI uygulama girişi
Çalıştır: uvicorn app:app --reload
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import init_db
from templates_config import templates

# ---------------------------------------------------------------------------
# Veritabanı başlat
# ---------------------------------------------------------------------------

_db_url = os.environ.get("DATABASE_URL", "")
if _db_url.startswith("postgres"):
    print("[DB] PostgreSQL bağlantısı kullanılıyor", flush=True)
elif not _db_url or _db_url.startswith("sqlite"):
    print("[DB] SQLite kullanılıyor", flush=True)

init_db()

# ---------------------------------------------------------------------------
# FastAPI uygulaması
# ---------------------------------------------------------------------------

app = FastAPI(
    title="E-dem — Ön Muhasebe Sistemi",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)

os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Nav-badge middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def nav_counts_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or "." in path.split("/")[-1]:
        request.state.nav_counts = {}
        return await call_next(request)

    counts = {}
    from auth import decode_token, COOKIE_NAME
    from database import SessionLocal
    from sqlalchemy import func
    from models import Invoice

    token = request.cookies.get(COOKIE_NAME)
    if token:
        payload = decode_token(token)
        if payload and payload.get("is_admin"):
            db = SessionLocal()
            try:
                counts["invoices_unpaid"] = (
                    db.query(func.count(Invoice.id))
                    .filter(Invoice.status.in_(["approved", "partial"]))
                    .scalar() or 0
                )
            except Exception:
                pass
            finally:
                db.close()

    request.state.nav_counts = counts
    return await call_next(request)


# ---------------------------------------------------------------------------
# Hata yöneticileri
# ---------------------------------------------------------------------------

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if exc.status_code == 403:
        return templates.TemplateResponse(
            "errors/403.html",
            {"request": request, "current_user": None, "detail": exc.detail},
            status_code=403,
        )
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "errors/404.html",
            {"request": request, "current_user": None},
            status_code=404,
        )
    return templates.TemplateResponse(
        "errors/generic.html",
        {"request": request, "current_user": None,
         "status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


# ---------------------------------------------------------------------------
# Kök yönlendirme
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Router'ları dahil et
# ---------------------------------------------------------------------------

from routers import auth as auth_router
from routers import dashboard as dashboard_router
from routers import references as references_router
from routers import customers as customers_router
from routers import users as users_router
from routers import invoices as invoices_router
from routers import vendors as vendors_router
from routers import cheques as cheques_router
from routers import cash as cash_router
from routers import bank_accounts as bank_accounts_router
from routers import credit_cards as credit_cards_router
from routers import general_expenses as general_expenses_router
from routers import employees as employees_router
from routers import reports as reports_router
from routers import hbf as hbf_router
from routers import advances as advances_router

app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(references_router.router)
app.include_router(customers_router.router)
app.include_router(users_router.router)
app.include_router(invoices_router.router)
app.include_router(vendors_router.router)
app.include_router(cheques_router.router)
app.include_router(cash_router.router)
app.include_router(bank_accounts_router.router)
app.include_router(credit_cards_router.router)
app.include_router(general_expenses_router.router)
app.include_router(employees_router.router)
app.include_router(reports_router.router)
app.include_router(hbf_router.router)
app.include_router(advances_router.router)
