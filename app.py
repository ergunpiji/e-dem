"""
E-dem — Ana FastAPI uygulama girişi
Çalıştır: uvicorn app:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import Base, engine, seed_data, migrate_db
from templates_config import templates

# ---------------------------------------------------------------------------
# Veritabanı başlat
# ---------------------------------------------------------------------------
import os as _os_db

_db_url = _os_db.environ.get("DATABASE_URL", "")
if _db_url.startswith("postgres"):
    print(f"[DB] PostgreSQL bağlantısı kullanılıyor ✓", flush=True)
elif _db_url.startswith("sqlite") or not _db_url:
    print(f"[DB] ⚠️  SQLite kullanılıyor — veriler her restart'ta SİLİNİR!", flush=True)
else:
    print(f"[DB] Bağlantı tipi: {_db_url[:20]}...", flush=True)

Base.metadata.create_all(bind=engine)
migrate_db()
seed_data()

# ---------------------------------------------------------------------------
# FastAPI uygulaması
# ---------------------------------------------------------------------------
app = FastAPI(
    title="E-dem — Etkinlik Talep Yönetim Sistemi",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ---------------------------------------------------------------------------
# Statik dosyalar
# ---------------------------------------------------------------------------
import os as _os
_os.makedirs("static/css", exist_ok=True)
_os.makedirs("static/js",  exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------------------------------------------------------------
# Hata yöneticileri
# ---------------------------------------------------------------------------

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        return RedirectResponse(
            url="/login",
            status_code=status.HTTP_302_FOUND,
        )
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
        {"request": request, "current_user": None, "status_code": exc.status_code, "detail": exc.detail},
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
from routers import users as users_router
from routers import venues as venues_router
from routers import customers as customers_router
from routers import services as services_router
from routers import requests as requests_router
from routers import budgets as budgets_router
from routers import event_types as event_types_router
from routers import settings as settings_router
from routers import reports as reports_router
from routers import invoices as invoices_router
from routers import email_templates as email_templates_router

app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(users_router.router)
app.include_router(venues_router.router)
app.include_router(customers_router.router)
app.include_router(services_router.router)
app.include_router(requests_router.router)
app.include_router(budgets_router.router)
app.include_router(event_types_router.router)
app.include_router(settings_router.router)
app.include_router(reports_router.router)
app.include_router(invoices_router.router)
app.include_router(email_templates_router.router)
