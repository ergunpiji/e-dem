"""
E-dem — Veritabanı bağlantısı ve başlangıç verisi
"""

import os
from datetime import datetime, date

from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import (
    Base, User, Customer, CashBook,
    GeneralExpenseCategory,
)

# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------

_raw_url = os.environ.get("DATABASE_URL", "sqlite:///./edem.db")
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _raw_url
_is_sqlite = DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict = {"echo": False}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 300
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 10

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

def seed_data() -> None:
    db = SessionLocal()
    try:
        # Admin kullanıcı
        if db.query(User).count() == 0:
            db.add(User(
                name="Admin",
                email="admin@edem.com",
                password_hash=_pwd_ctx.hash("Admin123"),
                is_admin=True,
                active=True,
            ))
            db.flush()
            print("[seed] Admin kullanıcı eklendi.")

        # Ana Kasa
        if db.query(CashBook).count() == 0:
            db.add(CashBook(name="Ana Kasa", currency="TRY"))
            db.flush()
            print("[seed] Ana Kasa eklendi.")

        # Genel Gider Kategorileri
        if db.query(GeneralExpenseCategory).count() == 0:
            cats = [
                ("Ofis Giderleri", 1, [
                    "Kira", "Elektrik & Doğalgaz", "Su", "İnternet & Telefon",
                    "Temizlik", "Kırtasiye & Sarf",
                ]),
                ("Pazarlama & Temsil", 2, [
                    "Reklam & Tanıtım", "Müşteri Ağırlama", "Fuar & Etkinlik",
                ]),
                ("Ulaşım & Seyahat", 3, [
                    "Yakıt", "Araç Bakım", "Uçak & Tren Bileti", "Konaklama",
                    "Taksi & Transfer",
                ]),
                ("Personel", 4, [
                    "Maaş", "SGK İşveren Payı", "Yan Haklar", "Avans",
                    "Eğitim & Gelişim",
                ]),
                ("Diğer", 5, [
                    "Hukuk & Danışmanlık", "Muhasebe", "Banka Masrafları",
                    "Vergi & Harçlar", "Diğer Giderler",
                ]),
            ]
            for cat_name, sort_order, sub_names in cats:
                parent = GeneralExpenseCategory(
                    name=cat_name, parent_id=None, sort_order=sort_order
                )
                db.add(parent)
                db.flush()
                for i, sub in enumerate(sub_names, 1):
                    db.add(GeneralExpenseCategory(
                        name=sub, parent_id=parent.id, sort_order=i
                    ))
            db.flush()
            print("[seed] Gider kategorileri eklendi.")

        db.commit()
        print("[seed] Tamamlandı.")
    except Exception as exc:
        db.rollback()
        print(f"[seed] HATA: {exc}")
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Referans no üretimi: TIP-MUS-YYMM-001
# ---------------------------------------------------------------------------

_EVENT_TYPE_CODES = {
    "toplanti": "TOP",
    "konferans": "KON",
    "gala": "GAL",
    "egitim": "EGT",
    "lansman": "LAN",
    "diger": "ETK",
}


def generate_ref_no(db, event_type: str, customer_code: str, check_in) -> str:
    from models import Reference
    tip = _EVENT_TYPE_CODES.get(event_type, "ETK")
    mus = (customer_code or "XXX").upper()[:3]
    if isinstance(check_in, str):
        try:
            check_in = date.fromisoformat(check_in)
        except Exception:
            check_in = date.today()
    yymm = check_in.strftime("%y%m")
    prefix = f"{tip}-{mus}-{yymm}-"
    count = db.query(Reference).filter(Reference.ref_no.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:03d}"


# ---------------------------------------------------------------------------
# Init (DB reset + create + seed)
# ---------------------------------------------------------------------------

def _migrate(engine) -> None:
    """Mevcut tablolara eksik kolonları ekler (basit migration)."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS due_date DATE",
    ]
    with engine.begin() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
            except Exception as e:
                print(f"[migrate] {sql[:60]}… → {e}")


def init_db() -> None:
    if os.environ.get("RESET_DB") == "1":
        print("[db] RESET_DB=1 — tablolar siliniyor...")
        Base.metadata.drop_all(bind=engine)
        print("[db] Tablolar silindi.")
    Base.metadata.create_all(bind=engine)
    _migrate(engine)
    print("[db] Tablolar hazır.")
    seed_data()


if __name__ == "__main__":
    init_db()
