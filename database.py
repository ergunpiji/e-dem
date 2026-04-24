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


def generate_hbf_no(db) -> str:
    from models import HBF
    from datetime import date as _date
    yymm = _date.today().strftime("%y%m")
    prefix = f"HBF-{yymm}-"
    count = db.query(HBF).filter(HBF.hbf_no.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:03d}"


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

    # PostgreSQL enum'a yeni değer eklemek transaction dışında yapılmalı
    if not DATABASE_URL.startswith("sqlite"):
        try:
            raw = engine.raw_connection()
            raw.set_isolation_level(0)  # AUTOCOMMIT
            cur = raw.cursor()
            cur.execute("ALTER TYPE invoice_status_enum ADD VALUE IF NOT EXISTS 'partial'")
            cur.close()
            raw.close()
            print("[migrate] invoice_status_enum 'partial' eklendi.")
        except Exception as e:
            print(f"[migrate] enum partial: {e}")

    migrations = [
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS due_date DATE",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS items_json TEXT",
        "ALTER TABLE financial_vendors ADD COLUMN IF NOT EXISTS address TEXT",
        "ALTER TABLE financial_vendors ADD COLUMN IF NOT EXISTS phone VARCHAR(50)",
        "ALTER TABLE financial_vendors ADD COLUMN IF NOT EXISTS email VARCHAR(200)",
        "ALTER TABLE financial_vendors ADD COLUMN IF NOT EXISTS payment_term INTEGER DEFAULT 30",
        "ALTER TABLE financial_vendors ADD COLUMN IF NOT EXISTS location_type VARCHAR(20) DEFAULT 'turkiye'",
        "ALTER TABLE financial_vendors ADD COLUMN IF NOT EXISTS cities TEXT",
        "ALTER TABLE financial_vendors ADD COLUMN IF NOT EXISTS bank_accounts_json TEXT",
        # VendorPrepayment yeni kolonlar
        "ALTER TABLE vendor_prepayments ADD COLUMN IF NOT EXISTS payment_type VARCHAR(20) DEFAULT 'prepayment'",
        "ALTER TABLE vendor_prepayments ADD COLUMN IF NOT EXISTS ref_id INTEGER",
        # Customer active alanı
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT true",
        # User is_approver alanı
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_approver BOOLEAN DEFAULT false",
        # EmployeeAdvance avans tipi ve iş avansı kapatma alanları
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS advance_type VARCHAR(10) DEFAULT 'maas'",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS ref_id INTEGER",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS expense_items_json TEXT",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS cash_return_amount FLOAT DEFAULT 0",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS closed_at DATE",
        "ALTER TABLE employee_advances ADD COLUMN IF NOT EXISTS closed_by INTEGER",
    ]
    with engine.begin() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
            except Exception as e:
                print(f"[migrate] {sql[:60]}… → {e}")


def _seed_extra_categories() -> None:
    """Eksik ana/alt kategorileri idempotent olarak ekler."""
    extra = [
        ("Personel (*)", 6, [
            "Bordro", "Elden", "Yan Haklar", "Sigorta", "Overtime",
            "Tazminat", "İkramiye/Prim", "Yönetim", "İsg & Eğitim",
            "Kıyafet", "Teşvik",
        ]),
        ("Genel Giderler", 7, [
            "Ofis Kira", "Ofis Gider", "Depo Kira", "Depo Gider",
            "Sigorta", "Araç", "Ulaşım", "İletişim", "It - Software",
            "It - Malzeme", "Temsil & Ağırlama", "Tanıtım", "Danışmanlık",
            "Resmi", "Bağış & Aidat", "Operasyonel Harcamalar",
        ]),
        ("Finans Giderleri", 8, [
            "Faiz", "Ortaklar Faizi", "Kredi Komisyonları", "Masraf",
        ]),
    ]
    db = SessionLocal()
    try:
        changed = False
        for cat_name, sort_order, sub_names in extra:
            parent = db.query(GeneralExpenseCategory).filter_by(
                name=cat_name, parent_id=None
            ).first()
            if not parent:
                parent = GeneralExpenseCategory(
                    name=cat_name, parent_id=None, sort_order=sort_order
                )
                db.add(parent)
                db.flush()
                changed = True
            for i, sub in enumerate(sub_names, 1):
                exists = db.query(GeneralExpenseCategory).filter_by(
                    name=sub, parent_id=parent.id
                ).first()
                if not exists:
                    db.add(GeneralExpenseCategory(
                        name=sub, parent_id=parent.id, sort_order=i
                    ))
                    changed = True
        if changed:
            db.commit()
            print("[seed] Ek gider kategorileri eklendi.")
    except Exception as exc:
        db.rollback()
        print(f"[seed] Ek kategoriler HATA: {exc}")
    finally:
        db.close()


def init_db() -> None:
    if os.environ.get("RESET_DB") == "1":
        print("[db] RESET_DB=1 — tablolar siliniyor...")
        Base.metadata.drop_all(bind=engine)
        print("[db] Tablolar silindi.")
    Base.metadata.create_all(bind=engine)
    _migrate(engine)
    print("[db] Tablolar hazır.")
    seed_data()
    _seed_extra_categories()


if __name__ == "__main__":
    init_db()
