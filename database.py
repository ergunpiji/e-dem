"""
E-dem — Veritabanı bağlantısı ve başlangıç verisi (seed)
"""

import json
from datetime import date, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models import (
    Base, User, Venue, Customer, Service, CustomCategory, Request, Budget,
    EventType, Settings, OrgTitle, Invoice, EmailTemplate,
    _EMAIL_TEMPLATE_DEFAULTS, _uuid, _now,
)

# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------

import os

_raw_url = os.environ.get("DATABASE_URL", "sqlite:///./edem.db")

# Railway / Render PostgreSQL URL'i "postgres://" ile başlar,
# SQLAlchemy "postgresql://" ister.
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _raw_url
_is_sqlite   = DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict = {"echo": False}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL: stale bağlantıları otomatik yenile (Railway idle timeout)
    _engine_kwargs["pool_pre_ping"]   = True
    _engine_kwargs["pool_recycle"]    = 300   # 5 dk'da bir bağlantıyı yenile
    _engine_kwargs["pool_size"]       = 5
    _engine_kwargs["max_overflow"]    = 10

engine = create_engine(DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

def seed_data() -> None:
    """Veritabanına başlangıç verisi ekler (varsa atlar)"""
    from passlib.context import CryptContext

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    db = SessionLocal()

    try:
        # ----------------------------------------------------------------
        # 1. Kullanıcılar
        # ----------------------------------------------------------------
        if db.query(User).count() == 0:
            users = [
                User(
                    id=_uuid(),
                    email="admin@edem.com",
                    password_hash=pwd_ctx.hash("Admin123"),
                    role="admin",
                    name="Admin",
                    surname="User",
                    title="Sistem Yöneticisi",
                    phone="+90 555 000 0001",
                    active=True,
                    created_at=_now(),
                ),
                User(
                    id=_uuid(),
                    email="manager@edem.com",
                    password_hash=pwd_ctx.hash("Manager123"),
                    role="project_manager",
                    name="Proje",
                    surname="Yöneticisi",
                    title="Proje Yöneticisi",
                    phone="+90 555 000 0002",
                    active=True,
                    created_at=_now(),
                ),
                User(
                    id=_uuid(),
                    email="edem@edem.com",
                    password_hash=pwd_ctx.hash("Edem123"),
                    role="e_dem",
                    name="E-dem",
                    surname="Kullanıcısı",
                    title="Satın Alma Uzmanı",
                    phone="+90 555 000 0003",
                    active=True,
                    created_at=_now(),
                ),
            ]
            db.add_all(users)
            db.flush()
            print("  [seed] Kullanıcılar eklendi.")

        # ----------------------------------------------------------------
        # 2. Etkinlik Tipleri
        # ----------------------------------------------------------------
        if db.query(EventType).count() == 0:
            event_types = [
                EventType(id=_uuid(), code='yi', label='Yurtiçi Etkinlik',           active=True, sort_order=1),
                EventType(id=_uuid(), code='yd', label='Yurtdışı Etkinlik',           active=True, sort_order=2),
                EventType(id=_uuid(), code='ut', label='Ürün Tanıtım Toplantısı',    active=True, sort_order=3),
                EventType(id=_uuid(), code='tk', label='Kongre Yönetimi',             active=True, sort_order=4),
                EventType(id=_uuid(), code='dk', label='Danışma Kurulu Toplantısı',  active=True, sort_order=5),
            ]
            db.add_all(event_types)
            db.flush()
            print("  [seed] Etkinlik tipleri eklendi.")

        # ----------------------------------------------------------------
        # 3. Müşteriler
        # ----------------------------------------------------------------
        if db.query(Customer).count() == 0:
            customers = [
                Customer(
                    id=_uuid(),
                    name="ABC Teknoloji A.Ş.",
                    code="abc",
                    sector="Teknoloji",
                    address="Maslak Mah. Büyükdere Cad. No:123 Sarıyer/İstanbul",
                    tax_office="Maslak",
                    tax_number="1234567890",
                    email="info@abcteknoloji.com",
                    phone="+90 212 555 0100",
                    notes="VIP müşteri",
                    contacts_json=json.dumps([
                        {"name": "Ayşe Kara",  "title": "Etkinlik Koordinatörü",  "email": "a.kara@abcteknoloji.com",  "phone": "+90 532 111 2233"},
                        {"name": "Mert Doğan", "title": "Genel Müdür Yardımcısı", "email": "m.dogan@abcteknoloji.com", "phone": "+90 532 111 4455"},
                    ], ensure_ascii=False),
                    created_at=_now(),
                ),
                Customer(
                    id=_uuid(),
                    name="XYZ Holding",
                    code="xyz",
                    sector="Finans",
                    address="Levent Mah. Nispetiye Cad. No:45 Beşiktaş/İstanbul",
                    tax_office="Levent",
                    tax_number="9876543210",
                    email="etkinlik@xyzholding.com",
                    phone="+90 212 444 0200",
                    notes="",
                    contacts_json=json.dumps([
                        {"name": "Selin Yıldız", "title": "Kurumsal İletişim Müdürü", "email": "s.yildiz@xyzholding.com", "phone": "+90 541 222 3344"},
                        {"name": "Burak Çelik",  "title": "İdari İşler Uzmanı",       "email": "b.celik@xyzholding.com",  "phone": "+90 541 222 5566"},
                    ], ensure_ascii=False),
                    created_at=_now(),
                ),
                Customer(
                    id=_uuid(),
                    name="DEF İnşaat Ltd. Şti.",
                    code="def",
                    sector="İnşaat",
                    address="Atatürk Cad. No:78 Kadıköy/İstanbul",
                    tax_office="Kadıköy",
                    tax_number="5566778899",
                    email="iletisim@definsaat.com",
                    phone="+90 216 333 0300",
                    notes="Aylık toplantı organizasyonu",
                    contacts_json=json.dumps([
                        {"name": "Hande Arslan", "title": "Proje Müdürü", "email": "h.arslan@definsaat.com",  "phone": "+90 553 333 7788"},
                        {"name": "Tolga Yılmaz", "title": "Genel Müdür",  "email": "t.yilmaz@definsaat.com", "phone": "+90 553 333 9900"},
                    ], ensure_ascii=False),
                    created_at=_now(),
                ),
            ]
            db.add_all(customers)
            db.flush()
            print("  [seed] Müşteriler eklendi.")

        # ----------------------------------------------------------------
        # 3. Tedarikçiler / Mekanlar
        # ----------------------------------------------------------------
        if db.query(Venue).count() == 0:
            venues = [
                Venue(
                    id=_uuid(),
                    name="Hilton İstanbul Bomonti",
                    city="İstanbul",
                    cities_json=json.dumps(["İstanbul"], ensure_ascii=False),
                    supplier_type="otel",
                    address="Silahşör Cad. No:42 Bomonti, Şişli/İstanbul",
                    stars=5,
                    total_rooms=829,
                    website="https://www.hilton.com",
                    notes="5 yıldızlı lüks otel, büyük konferans kapasitesi",
                    halls_json=json.dumps([
                        {"name": "Grand Ballroom", "capacity": 2000, "area": 2400},
                        {"name": "Bomonti Salonu", "capacity": 500,  "area": 600},
                        {"name": "Toplantı Odası A", "capacity": 50, "area": 80},
                        {"name": "Toplantı Odası B", "capacity": 30, "area": 50},
                    ], ensure_ascii=False),
                    contacts_json=json.dumps([
                        {"name": "Ahmet Yılmaz", "title": "Etkinlik Koordinatörü",
                         "email": "etkinlik@hiltonbomonti.com", "phone": "+90 212 375 3000"},
                        {"name": "Zeynep Kaya",  "title": "Satış Müdürü",
                         "email": "satis@hiltonbomonti.com", "phone": "+90 212 375 3001"},
                    ], ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                ),
                Venue(
                    id=_uuid(),
                    name="İstanbul Marriott Hotel Şişli",
                    city="İstanbul",
                    cities_json=json.dumps(["İstanbul"], ensure_ascii=False),
                    supplier_type="otel",
                    address="Büyükdere Cad. No:94 Şişli/İstanbul",
                    stars=5,
                    total_rooms=380,
                    website="https://www.marriott.com",
                    notes="Merkezi konumda, iş dünyasına yakın",
                    halls_json=json.dumps([
                        {"name": "Şişli Ballroom", "capacity": 800, "area": 900},
                        {"name": "Executive Lounge", "capacity": 100, "area": 120},
                        {"name": "Boardroom", "capacity": 20, "area": 40},
                    ], ensure_ascii=False),
                    contacts_json=json.dumps([
                        {"name": "Mehmet Demir", "title": "Event Manager",
                         "email": "events@marriottsisli.com", "phone": "+90 212 371 1500"},
                    ], ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                ),
                Venue(
                    id=_uuid(),
                    name="Conrad İstanbul Bosphorus",
                    city="İstanbul",
                    cities_json=json.dumps(["İstanbul"], ensure_ascii=False),
                    supplier_type="otel",
                    address="Yıldız Cad. No:13 Beşiktaş/İstanbul",
                    stars=5,
                    total_rooms=590,
                    website="https://www.conradistanbul.com",
                    notes="Boğaz manzaralı lüks otel",
                    halls_json=json.dumps([
                        {"name": "Conrad Ballroom", "capacity": 1200, "area": 1400},
                        {"name": "Bosphorus Hall", "capacity": 400, "area": 500},
                        {"name": "Meeting Room 1",  "capacity": 40,  "area": 60},
                        {"name": "Meeting Room 2",  "capacity": 25,  "area": 40},
                    ], ensure_ascii=False),
                    contacts_json=json.dumps([
                        {"name": "Ayşe Şahin", "title": "Banquet & Events Manager",
                         "email": "events@conradistanbul.com", "phone": "+90 212 310 2525"},
                        {"name": "Caner Öztürk", "title": "Groups Coordinator",
                         "email": "groups@conradistanbul.com", "phone": "+90 212 310 2526"},
                    ], ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                ),
                Venue(
                    id=_uuid(),
                    name="ProAV Teknik Ekipman",
                    city="İstanbul",
                    cities_json=json.dumps(["İstanbul", "Ankara", "İzmir"], ensure_ascii=False),
                    supplier_type="teknik",
                    address="Dudullu OSB Mah. Nato Yolu Cad. No:5 Ümraniye/İstanbul",
                    stars=None,
                    total_rooms=0,
                    website="https://www.proav.com.tr",
                    notes="Ses, ışık, projeksiyon ekipmanı kiralama ve kurulum",
                    halls_json=json.dumps([], ensure_ascii=False),
                    contacts_json=json.dumps([
                        {"name": "Serkan Arslan", "title": "Teknik Koordinatör",
                         "email": "teknik@proav.com.tr", "phone": "+90 216 450 0101"},
                    ], ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                ),
                Venue(
                    id=_uuid(),
                    name="Flash Transfer",
                    city="İstanbul",
                    cities_json=json.dumps(["İstanbul", "Ankara"], ensure_ascii=False),
                    supplier_type="transfer",
                    address="Atatürk Havalimanı Yanı, Bakırköy/İstanbul",
                    stars=None,
                    total_rooms=0,
                    website="https://www.flashtransfer.com.tr",
                    notes="VIP transfer, kafile transferi, havalimanı karşılama",
                    halls_json=json.dumps([], ensure_ascii=False),
                    contacts_json=json.dumps([
                        {"name": "Hakan Güneş", "title": "Operasyon Müdürü",
                         "email": "ops@flashtransfer.com.tr", "phone": "+90 212 555 7070"},
                    ], ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                ),
            ]
            db.add_all(venues)
            db.flush()
            print("  [seed] Tedarikçiler eklendi.")

        # ----------------------------------------------------------------
        # 4. Hizmet Kataloğu
        # ----------------------------------------------------------------
        if db.query(Service).count() == 0:
            services_data = [
                # Konaklama
                ("accommodation", "Standart Oda SGL (Tek Kişilik)", "Gece"),
                ("accommodation", "Standart Oda DBL (Çift Kişilik)", "Gece"),
                ("accommodation", "Superior Oda SGL", "Gece"),
                ("accommodation", "Superior Oda DBL", "Gece"),
                ("accommodation", "Deluxe Oda", "Gece"),
                ("accommodation", "Suite Oda", "Gece"),
                ("accommodation", "Ekstra Yatak", "Gece"),
                # Toplantı / Salon
                ("meeting", "Salon Kiralama (Tam Gün)", "Salon/Gün"),
                ("meeting", "Salon Kiralama (Yarım Gün)", "Salon/Yarım Gün"),
                ("meeting", "Projeksiyon ve Perde", "Adet/Gün"),
                ("meeting", "Ses Sistemi (Mikrofon Dahil)", "Set/Gün"),
                ("meeting", "LED Ekran (P2.5 veya P3)", "m²/Gün"),
                ("meeting", "Simultane Çeviri Sistemi", "Set/Gün"),
                ("meeting", "Video Kayıt Hizmeti", "Gün"),
                ("meeting", "Canlı Yayın (Streaming)", "Gün"),
                # F&B
                ("fb", "Kahvaltı (Açık Büfe)", "Kişi"),
                ("fb", "Öğle Yemeği (Açık Büfe)", "Kişi"),
                ("fb", "Akşam Yemeği (Açık Büfe)", "Kişi"),
                ("fb", "Gala Yemeği", "Kişi"),
                ("fb", "Coffee Break (Sabah)", "Kişi"),
                ("fb", "Coffee Break (Öğleden Sonra)", "Kişi"),
                ("fb", "Welcome Drink Kokteyli", "Kişi"),
                ("fb", "Set Menü (3 Kurs)", "Kişi"),
                # Teknik
                ("teknik", "Ses Sistemi (Hat Array)", "Set/Gün"),
                ("teknik", "Işık Platformu (Wash + Spot)", "Set/Gün"),
                ("teknik", "Sahne Montajı (Modüler)", "m²"),
                ("teknik", "Projeksiyon (10,000 ANSI Lümen)", "Adet/Gün"),
                ("teknik", "LED Dış Mekan Ekranı", "m²/Gün"),
                ("teknik", "Teknik Ekip (Teknisyen)", "Kişi/Gün"),
                # Transfer
                ("transfer", "VIP Araç (Sedan/Vito)", "Araç/Gün"),
                ("transfer", "Otobüs Transfer (Kapasite 50)", "Araç/Gün"),
                ("transfer", "Minibüs Transfer (Kapasite 20)", "Araç/Gün"),
                ("transfer", "Havalimanı Karşılama & Uğurlama", "Transfer"),
                ("transfer", "Şehir İçi Transfer", "Transfer"),
                # Diğer
                ("other", "Fotoğrafçı (Kurumsal)", "Gün"),
                ("other", "Video Çekimi & Kurgu", "Gün"),
                ("other", "Hostess (Karşılama)", "Kişi/Gün"),
                ("other", "Tercüman (İngilizce)", "Kişi/Gün"),
                ("other", "Çiçek Düzenlemesi", "Adet"),
                ("other", "Davetiye Tasarım & Baskı", "Adet"),
            ]
            services = [
                Service(id=_uuid(), category=cat, name=name, unit=unit, active=True)
                for cat, name, unit in services_data
            ]
            db.add_all(services)
            db.flush()
            print("  [seed] Hizmet kataloğu eklendi.")

        # ----------------------------------------------------------------
        # 5. Organizasyon Unvanları
        # ----------------------------------------------------------------
        if db.query(OrgTitle).count() == 0:
            id_gm   = _uuid(); id_gmy  = _uuid(); id_dir  = _uuid()
            id_egm  = _uuid(); id_esym = _uuid(); id_artd = _uuid(); id_fmbm = _uuid()
            id_ebm  = _uuid(); id_tsyk = _uuid(); id_dyk  = _uuid(); id_lok  = _uuid()
            id_gtym = _uuid(); id_fm   = _uuid(); id_mm   = _uuid()
            id_pym  = _uuid(); id_gtyk = _uuid(); id_fy   = _uuid(); id_my   = _uuid()
            id_ps   = _uuid(); id_pa   = _uuid()

            org_titles = [
                OrgTitle(id=id_gm,   name="Genel Müdür",                       grade=1, parent_id=None,    budget_limit=None, sort_order=1),
                OrgTitle(id=id_gmy,  name="Genel Müdür Yardımcısı",            grade=2, parent_id=id_gm,   budget_limit=None, sort_order=2),
                OrgTitle(id=id_dir,  name="Direktör",                          grade=3, parent_id=id_gmy,  budget_limit=None, sort_order=3),
                OrgTitle(id=id_egm,  name="Etkinlik Grup Müdürü",              grade=4, parent_id=id_dir,  budget_limit=None, sort_order=4),
                OrgTitle(id=id_esym, name="Etkinlik Süreç Yönetimi Müdürü",   grade=4, parent_id=id_dir,  budget_limit=None, sort_order=5),
                OrgTitle(id=id_artd, name="Art Direktör",                      grade=4, parent_id=id_dir,  budget_limit=None, sort_order=6),
                OrgTitle(id=id_fmbm, name="Finans ve Muhasebe Birimi Müdürü", grade=4, parent_id=id_dir,  budget_limit=None, sort_order=7),
                OrgTitle(id=id_ebm,  name="Etkinlik Birim Müdürü",             grade=5, parent_id=id_egm,  budget_limit=None, sort_order=8),
                OrgTitle(id=id_tsyk, name="Teknik Servisler Yetkilisi",        grade=5, parent_id=id_esym, budget_limit=None, sort_order=9),
                OrgTitle(id=id_dyk,  name="Dekor Yetkilisi",                   grade=5, parent_id=id_esym, budget_limit=None, sort_order=10),
                OrgTitle(id=id_lok,  name="Lojistik Yetkilisi",                grade=5, parent_id=id_esym, budget_limit=None, sort_order=11),
                OrgTitle(id=id_gtym, name="Grafik Tasarım Yöneticisi",         grade=5, parent_id=id_artd, budget_limit=None, sort_order=12),
                OrgTitle(id=id_fm,   name="Finans Müdürü",                     grade=5, parent_id=id_fmbm, budget_limit=None, sort_order=13),
                OrgTitle(id=id_mm,   name="Muhasebe Müdürü",                   grade=5, parent_id=id_fmbm, budget_limit=None, sort_order=14),
                OrgTitle(id=id_pym,  name="Proje Yöneticisi",                  grade=6, parent_id=id_ebm,  budget_limit=None, sort_order=15),
                OrgTitle(id=id_gtyk, name="Grafik Tasarım Yetkilisi",          grade=6, parent_id=id_gtym, budget_limit=None, sort_order=16),
                OrgTitle(id=id_fy,   name="Finans Yetkilisi",                  grade=6, parent_id=id_fm,   budget_limit=None, sort_order=17),
                OrgTitle(id=id_my,   name="Muhasebe Yetkilisi",                grade=6, parent_id=id_mm,   budget_limit=None, sort_order=18),
                OrgTitle(id=id_ps,   name="Proje Sorumlusu",                   grade=7, parent_id=id_pym,  budget_limit=None, sort_order=19),
                OrgTitle(id=id_pa,   name="Proje Asistanı",                    grade=8, parent_id=id_ps,   budget_limit=None, sort_order=20),
            ]
            db.add_all(org_titles)
            db.flush()
            print("  [seed] Organizasyon unvanları eklendi.")

        # Sistem ayarları
        if db.query(Settings).count() == 0:
            db.add(Settings(
                id=1,
                company_name="E-dem Etkinlik Yönetimi",
                company_address="",
                company_phone="",
                company_email="",
                logo_url="",
                email_signature="",
                rfq_subject_tpl="{event_name} Fiyat Teklifi - {request_no}",
                currency="₺",
            ))
            db.flush()
            print("  [seed] Sistem ayarları eklendi.")

        # E-posta şablonları
        for tpl_data in _EMAIL_TEMPLATE_DEFAULTS:
            if not db.query(EmailTemplate).filter(EmailTemplate.slug == tpl_data["slug"]).first():
                db.add(EmailTemplate(
                    id=_uuid(),
                    slug=tpl_data["slug"],
                    name=tpl_data["name"],
                    description=tpl_data["description"],
                    subject_tpl=tpl_data["subject_tpl"],
                    body_tpl=tpl_data["body_tpl"],
                    active=True,
                    created_at=_now(),
                    updated_at=_now(),
                ))
        db.flush()
        print("  [seed] E-posta şablonları eklendi.")

        db.commit()
        print("  [seed] Tamamlandı.")

    except Exception as exc:
        db.rollback()
        print(f"  [seed] HATA: {exc}")
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Yardımcı fonksiyon: referans no üretimi
# ---------------------------------------------------------------------------

def generate_ref_no(db, event_type_code: str, customer_code: str, check_in_str: str) -> str:
    """Talep referans numarası üretir: yi abc 010426 a"""
    import string as _string
    try:
        check_in = date.fromisoformat(check_in_str)
        ddmmyy = check_in.strftime("%d%m%y")
    except Exception:
        ddmmyy = date.today().strftime("%d%m%y")

    code   = (event_type_code or "yi").lower()
    mus    = (customer_code or "xxx").lower()[:3]
    prefix = f"{code} {mus} {ddmmyy}"

    # Find existing refs with same prefix to determine next letter
    existing = db.query(Request).filter(
        Request.request_no.like(f"{prefix} %")
    ).all()

    used_letters = set()
    for r in existing:
        parts = r.request_no.split(" ")
        if len(parts) == 4:
            used_letters.add(parts[3])

    for letter in _string.ascii_lowercase:
        if letter not in used_letters:
            return f"{prefix} {letter}"

    return f"{prefix} z"  # fallback


# ---------------------------------------------------------------------------
# Veritabanı migrasyon (mevcut tablolara yeni sütun ekler)
# ---------------------------------------------------------------------------

def _col_exists(conn, table: str, column: str) -> bool:
    """Sütunun tabloda var olup olmadığını kontrol eder (SQLite + PostgreSQL)."""
    if _is_sqlite:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == column for r in rows)
    else:
        row = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ), {"t": table, "c": column}).fetchone()
        return row is not None


def _safe_add_column(conn, table: str, column: str, col_type: str, default: str | None = None) -> None:
    """Sütun yoksa ekler, varsa sessizce geçer."""
    if _col_exists(conn, table, column):
        return
    default_sql = f" DEFAULT {default}" if default is not None else ""
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_sql}"))
    conn.commit()


def _seed_email_templates() -> None:
    """email_templates tablosuna eksik varsayılan şablonları ekler (idempotent)."""
    db = SessionLocal()
    try:
        for tpl_data in _EMAIL_TEMPLATE_DEFAULTS:
            if not db.query(EmailTemplate).filter(EmailTemplate.slug == tpl_data["slug"]).first():
                db.add(EmailTemplate(
                    id=_uuid(),
                    slug=tpl_data["slug"],
                    name=tpl_data["name"],
                    description=tpl_data["description"],
                    subject_tpl=tpl_data["subject_tpl"],
                    body_tpl=tpl_data["body_tpl"],
                    active=True,
                    created_at=_now(),
                    updated_at=_now(),
                ))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def migrate_db():
    """Mevcut tablolara eksik sütunları ekler (SQLite + PostgreSQL uyumlu)."""
    with engine.connect() as conn:
        _safe_add_column(conn, "customers", "contacts_json",       "TEXT", "'{}'")
        _safe_add_column(conn, "requests",  "contact_person_json", "TEXT", "'{}'")
        _safe_add_column(conn, "users",     "org_title_id",        "TEXT")
        _safe_add_column(conn, "users",     "avatar_b64",          "TEXT", "''")
        _safe_add_column(conn, "invoices",  "lines_json",          "TEXT", "'[]'")

        # Budgets
        _safe_add_column(conn, "budgets", "budget_status",       "TEXT",  "'draft_edem'")
        _safe_add_column(conn, "budgets", "revision_notes",      "TEXT",  "''")
        _safe_add_column(conn, "budgets", "manager_notes",       "TEXT",  "''")
        _safe_add_column(conn, "budgets", "service_fee_pct",     "REAL",  "0")
        _safe_add_column(conn, "budgets", "offer_currency",      "TEXT",  "'TRY'")
        _safe_add_column(conn, "budgets", "exchange_rates_json", "TEXT",  "'{}'")
        _safe_add_column(conn, "budgets", "venue_id",              "TEXT")
        _safe_add_column(conn, "budgets", "price_history_json",   "TEXT", "'[]'")
        _safe_add_column(conn, "budgets", "price_snapshots_json",  "TEXT", "'[]'")

        # Requests — post-offer workflow
        _safe_add_column(conn, "requests", "confirmed_at",        "TIMESTAMP")
        _safe_add_column(conn, "requests", "confirmed_budget_id", "TEXT")
        _safe_add_column(conn, "requests", "cancellation_reason", "TEXT",    "''")
        _safe_add_column(conn, "requests", "revision_count",      "INTEGER", "0")

        # Customers
        _safe_add_column(conn, "customers", "excel_template_path", "TEXT", "''")
        _safe_add_column(conn, "customers", "excel_template_b64",  "TEXT", "''")
        _safe_add_column(conn, "customers", "excel_config_json",   "TEXT", "'{}'")
        _safe_add_column(conn, "customers", "docs_json",           "TEXT", "'[]'")

        # Invoices tablosu — yoksa oluştur
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id            TEXT PRIMARY KEY,
                    request_id    TEXT NOT NULL REFERENCES requests(id),
                    invoice_type  TEXT NOT NULL,
                    invoice_no    TEXT DEFAULT '',
                    invoice_date  TEXT,
                    due_date      TEXT,
                    vendor_name   TEXT DEFAULT '',
                    description   TEXT DEFAULT '',
                    amount        REAL DEFAULT 0.0,
                    vat_rate      REAL DEFAULT 20.0,
                    vat_amount    REAL DEFAULT 0.0,
                    total_amount  REAL DEFAULT 0.0,
                    document_path TEXT,
                    document_name TEXT,
                    status        TEXT DEFAULT 'active',
                    created_by    TEXT NOT NULL REFERENCES users(id),
                    created_at    TIMESTAMP,
                    updated_at    TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_invoices_request_id ON invoices(request_id)"
            ))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id            VARCHAR(36) PRIMARY KEY,
                    request_id    VARCHAR(36) NOT NULL REFERENCES requests(id),
                    invoice_type  VARCHAR(32) NOT NULL,
                    invoice_no    VARCHAR(100) DEFAULT '',
                    invoice_date  VARCHAR(10),
                    due_date      VARCHAR(10),
                    vendor_name   VARCHAR(255) DEFAULT '',
                    description   TEXT DEFAULT '',
                    amount        FLOAT DEFAULT 0.0,
                    vat_rate      FLOAT DEFAULT 20.0,
                    vat_amount    FLOAT DEFAULT 0.0,
                    total_amount  FLOAT DEFAULT 0.0,
                    document_path VARCHAR(500),
                    document_name VARCHAR(255),
                    status        VARCHAR(16) DEFAULT 'active',
                    created_by    VARCHAR(36) NOT NULL REFERENCES users(id),
                    created_at    TIMESTAMP,
                    updated_at    TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_invoices_request_id ON invoices(request_id)"
            ))
        # email_templates tablosu — yoksa oluştur
        if _is_sqlite:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS email_templates (
                    id          TEXT PRIMARY KEY,
                    slug        TEXT UNIQUE NOT NULL,
                    name        TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    subject_tpl TEXT NOT NULL,
                    body_tpl    TEXT NOT NULL,
                    active      INTEGER DEFAULT 1,
                    created_at  TIMESTAMP,
                    updated_at  TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS email_templates (
                    id          VARCHAR(36) PRIMARY KEY,
                    slug        VARCHAR(64) UNIQUE NOT NULL,
                    name        VARCHAR(200) NOT NULL,
                    description VARCHAR(400) DEFAULT '',
                    subject_tpl VARCHAR(400) NOT NULL,
                    body_tpl    TEXT NOT NULL,
                    active      BOOLEAN DEFAULT TRUE,
                    created_at  TIMESTAMP,
                    updated_at  TIMESTAMP
                )
            """))
        conn.commit()

        # Eksik seed şablonlarını ekle (idempotent)
        _seed_email_templates()

    # Müşterilere kontak kişi ekle — kontak yoksa HER ZAMAN güncelle
    SEED_CONTACTS = {
        "abc": [
            {"name": "Ayşe Kara",    "title": "Etkinlik Koordinatörü",  "email": "a.kara@abcteknoloji.com",  "phone": "+90 532 111 2233"},
            {"name": "Mert Doğan",   "title": "Genel Müdür Yardımcısı", "email": "m.dogan@abcteknoloji.com", "phone": "+90 532 111 4455"},
        ],
        "xyz": [
            {"name": "Selin Yıldız", "title": "Kurumsal İletişim Müdürü", "email": "s.yildiz@xyzholding.com", "phone": "+90 541 222 3344"},
            {"name": "Burak Çelik",  "title": "İdari İşler Uzmanı",       "email": "b.celik@xyzholding.com",  "phone": "+90 541 222 5566"},
        ],
        "def": [
            {"name": "Hande Arslan", "title": "Proje Müdürü", "email": "h.arslan@definsaat.com",  "phone": "+90 553 333 7788"},
            {"name": "Tolga Yılmaz", "title": "Genel Müdür",  "email": "t.yilmaz@definsaat.com",  "phone": "+90 553 333 9900"},
        ],
    }
    db_c = SessionLocal()
    try:
        for cust_code, contacts in SEED_CONTACTS.items():
            c = db_c.query(Customer).filter(Customer.code == cust_code).first()
            if not c:
                continue
            # Mevcut kontak sayısını kontrol et — boşsa güncelle
            try:
                existing = json.loads(c.contacts_json or "[]")
            except Exception:
                existing = []
            if not existing:
                c.contacts_json = json.dumps(contacts, ensure_ascii=False)
                print(f"  [migrate] {cust_code} kontakları eklendi.")
        db_c.commit()
    except Exception as e:
        db_c.rollback()
        print(f"  [migrate] Kontak ekleme hatası: {e}")
    finally:
        db_c.close()

    # Sonradan eklenen org unvanları
    db = SessionLocal()
    try:
        fmbm = db.query(OrgTitle).filter(OrgTitle.name == "Finans ve Muhasebe Birimi Müdürü").first()
        if fmbm and not db.query(OrgTitle).filter(OrgTitle.name == "Satın Alma Müdürü").first():
            sam = OrgTitle(id=_uuid(), name="Satın Alma Müdürü", grade=5,
                           parent_id=fmbm.id, budget_limit=None, sort_order=14)
            db.add(sam)
            db.flush()
            db.add(OrgTitle(id=_uuid(), name="Satın Alma Yetkilisi", grade=6,
                            parent_id=sam.id, budget_limit=None, sort_order=18))
            db.commit()
            print("  [migrate] Satın Alma unvanları eklendi.")
    except Exception as e:
        db.rollback()
        print(f"  [migrate] Satın Alma unvanları eklenemedi: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    print("Tablolar oluşturuluyor...")
    Base.metadata.create_all(engine)
    print("Seed data ekleniyor...")
    seed_data()
    print("Hazır.")
