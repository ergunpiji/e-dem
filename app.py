"""
E-dem — Ana FastAPI uygulama girişi
Çalıştır: uvicorn app:app --reload
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# prizma-einvoice paketini sys.path'e ekle (editable install yerine)
_pkg_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "packages", "prizma-einvoice", "src",
)
if os.path.isdir(_pkg_path) and _pkg_path not in sys.path:
    sys.path.insert(0, _pkg_path)

from fastapi import FastAPI, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import init_db, engine, get_db
from models import Base
from auth import get_current_user, require_admin
from templates_config import templates

# E-Fatura modülünü init et — register_models Base'e tablolar ekler.
# init_db()'den ÖNCE yapılmalı ki create_all yeni tabloları da yaratsın.
try:
    from prizma_einvoice import EInvoiceModule
    einvoice_module = EInvoiceModule(
        host_base=Base,
        engine=engine,
        config={"provider": "fake"},
        get_db_dependency=get_db,
        require_admin_dependency=require_admin,
        get_current_user_dependency=get_current_user,
    )
    print("[einvoice] modül init edildi (provider: fake)", flush=True)
except Exception as exc:  # noqa: BLE001
    einvoice_module = None
    print(f"[einvoice] modül init edilemedi: {exc}", flush=True)

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
        request.state.enabled_modules = set()
        return await call_next(request)

    counts = {}
    enabled_modules = set()
    from auth import decode_token, COOKIE_NAME
    from database import SessionLocal
    from sqlalchemy import func
    from models import Invoice, PaymentInstruction, SystemSetting

    token = request.cookies.get(COOKIE_NAME)
    if token:
        payload = decode_token(token)
        if payload:
            db = SessionLocal()
            try:
                if payload.get("is_admin"):
                    counts["invoices_unpaid"] = (
                        db.query(func.count(Invoice.id))
                        .filter(Invoice.status.in_(["approved", "partial"]))
                        .scalar() or 0
                    )
                counts["pending_instructions"] = (
                    db.query(func.count(PaymentInstruction.id))
                    .filter(PaymentInstruction.status == "pending")
                    .scalar() or 0
                )
                # Aktif modülleri oku (Yönetim → Modüller'den ayarlanır)
                module_settings = db.query(SystemSetting).filter(
                    SystemSetting.key.like("module_%_enabled")
                ).all()
                for s in module_settings:
                    if s.value == "1":
                        # 'module_einvoice_enabled' → 'einvoice'
                        key = s.key[len("module_"):-len("_enabled")]
                        enabled_modules.add(key)
            except Exception:
                pass
            finally:
                db.close()

    request.state.nav_counts = counts
    request.state.enabled_modules = enabled_modules
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
from routers import payments as payments_router
from routers import payment_instructions as payment_instructions_router
from routers import profile as profile_router
from routers import admin_modules as admin_modules_router
from routers import einvoice_host as einvoice_host_router
from routers import tax_reports as tax_reports_router
from routers import edefter as edefter_router

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
app.include_router(payments_router.router)
app.include_router(payment_instructions_router.router)
app.include_router(profile_router.router)
app.include_router(admin_modules_router.router)
app.include_router(einvoice_host_router.router)
app.include_router(tax_reports_router.router)
app.include_router(edefter_router.router)

# E-Fatura modülünü mount et (router /einvoice/* prefix'ile eklenir).
# Endpoint'ler her zaman erişilebilir; aktif/pasif kontrolü feature flag ile
# (admin_modules sayfasından) yönetilir.
if einvoice_module is not None:
    try:
        einvoice_module.install(app)
        print("[einvoice] router /einvoice/* mount edildi", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[einvoice] router mount edilemedi: {exc}", flush=True)
