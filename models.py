"""
E-dem — Etkinlik Talep Yönetim Sistemi
SQLAlchemy modelleri ve uygulama sabitleri
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, Float
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

SUPPLIER_TYPES = [
    {"value": "otel",       "label": "Otel"},
    {"value": "etkinlik",   "label": "Etkinlik Mekanı"},
    {"value": "restaurant", "label": "Restoran"},
    {"value": "teknik",     "label": "Teknik Ekipman"},
    {"value": "dekor",      "label": "Dekor / Süsleme"},
    {"value": "transfer",   "label": "Transfer / Ulaşım"},
    {"value": "tasarim",    "label": "Tasarım & Baskı"},
    {"value": "susleme",    "label": "Süsleme"},
    {"value": "ik",         "label": "İnsan Kaynakları"},
    {"value": "diger",      "label": "Diğer"},
]

REQUEST_STATUSES = [
    {"value": "draft",             "label": "Taslak",                   "color": "secondary"},
    {"value": "pending",           "label": "Beklemede",                 "color": "warning"},
    {"value": "in_progress",       "label": "İşlemde",                   "color": "primary"},
    {"value": "venues_contacted",  "label": "Mekanlarla İletişime Geçildi", "color": "info"},
    {"value": "budget_ready",      "label": "Bütçe Hazır",               "color": "success"},
    {"value": "offer_sent",        "label": "Teklif Gönderildi",         "color": "teal"},
    {"value": "confirmed",         "label": "Müşteri Onayladı",          "color": "success"},
    {"value": "revision",          "label": "Revizyon",                  "color": "warning"},
    {"value": "completed",         "label": "Tamamlandı",                "color": "success"},
    {"value": "cancelled",         "label": "İptal Edildi",              "color": "danger"},
    {"value": "postponed",         "label": "Ertelendi",                 "color": "secondary"},
]

REQUEST_STATUS_COLORS = {s["value"]: s["color"] for s in REQUEST_STATUSES}
REQUEST_STATUS_LABELS = {s["value"]: s["label"] for s in REQUEST_STATUSES}

REQUEST_TABS = [
    {
        "id": "venue",
        "label": "🏨 Otel / Mekan",
        "supplier_types": ["otel", "etkinlik"],
        "sections": ["accommodation", "meeting", "fb"],
    },
    {
        "id": "teknik",
        "label": "🔧 Teknik Ekipman",
        "supplier_types": ["teknik"],
        "sections": ["teknik"],
    },
    {
        "id": "dekor",
        "label": "🎨 Dekor",
        "supplier_types": ["dekor"],
        "sections": ["dekor"],
    },
    {
        "id": "transfer",
        "label": "🚌 Ulaşım & Transferler",
        "supplier_types": ["transfer"],
        "sections": ["transfer"],
    },
    {
        "id": "tasarim",
        "label": "🖨 Tasarım & Basılı",
        "supplier_types": ["tasarim"],
        "sections": ["tasarim"],
    },
    {
        "id": "diger",
        "label": "📦 Diğer Servisler",
        "supplier_types": ["restaurant", "susleme", "ik", "diger"],
        "sections": ["other"],
    },
]

SEATING_LAYOUTS = [
    {"value": "tiyatro",    "label": "Tiyatro Düzeni"},
    {"value": "sinif",      "label": "Sınıf Düzeni"},
    {"value": "u-seklinde", "label": "U Şeklinde"},
    {"value": "toplanti",   "label": "Toplantı Düzeni"},
    {"value": "adatr",      "label": "Ada / Roundtable"},
    {"value": "kokteyl",    "label": "Kokteyl"},
    {"value": "gala",       "label": "Gala Oturma"},
]

EVENT_TYPES = [
    {"value": "toplanti",  "label": "Toplantı"},
    {"value": "konferans", "label": "Konferans"},
    {"value": "gala",      "label": "Gala"},
    {"value": "egitim",    "label": "Eğitim"},
    {"value": "lansman",   "label": "Lansman"},
    {"value": "diger",     "label": "Diğer"},
]

EVENT_TYPE_CODES = {
    "toplanti": "TOP",
    "konferans": "KON",
    "gala":      "GAL",
    "egitim":    "EGT",
    "lansman":   "LAN",
    "diger":     "ETK",
}


USER_ROLES = [
    {"value": "admin",             "label": "Admin"},
    {"value": "project_manager",   "label": "Proje Yöneticisi"},
    {"value": "e_dem",             "label": "E-dem (Satın Alma)"},
    {"value": "muhasebe_muduru",   "label": "Muhasebe Müdürü"},
    {"value": "muhasebe",          "label": "Muhasebe Yetkilisi"},
]

USER_ROLE_LABELS = {r["value"]: r["label"] for r in USER_ROLES}

INVOICE_TYPES = [
    {"value": "kesilen",       "label": "Kesilen Fatura (Müşteriye)"},
    {"value": "gelen",         "label": "Gelen Fatura (Tedarikçiden)"},
    {"value": "komisyon",      "label": "Komisyon Faturası"},
    {"value": "iade_kesilen",  "label": "İade — Kesilen Fatura"},
    {"value": "iade_gelen",    "label": "İade — Gelen Fatura"},
]

INVOICE_TYPE_LABELS = {t["value"]: t["label"] for t in INVOICE_TYPES}

SERVICE_CATEGORIES = [
    {"id": "accommodation", "label": "Konaklama",        "icon": "🛏",  "color": "primary"},
    {"id": "meeting",       "label": "Toplantı / Salon", "icon": "🏛",  "color": "success"},
    {"id": "fb",            "label": "F&B (Yiyecek & İçecek)", "icon": "🍽", "color": "warning"},
    {"id": "teknik",        "label": "Teknik",           "icon": "🔧",  "color": "danger"},
    {"id": "dekor",         "label": "Dekor",            "icon": "🎨",  "color": "pink"},
    {"id": "transfer",      "label": "Transfer",         "icon": "🚌",  "color": "info"},
    {"id": "tasarim",       "label": "Tasarım & Baskı",  "icon": "🖨",  "color": "green"},
    {"id": "other",         "label": "Diğer",            "icon": "📦",  "color": "purple"},
]

TR_CITIES = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Amasya", "Ankara", "Antalya", "Artvin",
    "Aydın", "Balıkesir", "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur", "Bursa", "Çanakkale",
    "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Edirne", "Elazığ", "Erzincan", "Erzurum",
    "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Isparta", "Mersin",
    "İstanbul", "İzmir", "Kars", "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir", "Kocaeli",
    "Konya", "Kütahya", "Malatya", "Manisa", "Kahramanmaraş", "Mardin", "Muğla", "Muş",
    "Nevşehir", "Niğde", "Ordu", "Rize", "Sakarya", "Samsun", "Siirt", "Sinop", "Sivas",
    "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Şanlıurfa", "Uşak", "Van", "Yozgat", "Zonguldak",
    "Aksaray", "Bayburt", "Karaman", "Kırıkkale", "Batman", "Şırnak", "Bartın", "Ardahan",
    "Iğdır", "Yalova", "Karabük", "Kilis", "Osmaniye", "Düzce",
]

VAT_RATES = [0, 1, 8, 10, 18, 20]


# ---------------------------------------------------------------------------
# SQLAlchemy Modelleri
# ---------------------------------------------------------------------------

class OrgTitle(Base):
    """Organizasyon unvanları — hiyerarşik yapı ve bütçe limitleri"""
    __tablename__ = "org_titles"

    id           = Column(String(36), primary_key=True, default=_uuid)
    name         = Column(String(150), nullable=False)
    grade        = Column(Integer, nullable=False, default=1)   # 1=en üst, yüksek=alt
    parent_id    = Column(String(36), ForeignKey("org_titles.id"), nullable=True)
    budget_limit = Column(Float, nullable=True)                  # None = limitsiz
    sort_order   = Column(Integer, default=0)

    parent   = relationship("OrgTitle", remote_side="OrgTitle.id", back_populates="children",
                            foreign_keys="OrgTitle.parent_id")
    children = relationship("OrgTitle", back_populates="parent",
                            foreign_keys="OrgTitle.parent_id")
    users    = relationship("User", back_populates="org_title")

    @property
    def budget_limit_display(self) -> str:
        if self.budget_limit is None:
            return "Limitsiz"
        return f"₺{self.budget_limit:,.0f}".replace(",", ".")


class EventType(Base):
    """DB-tabanlı etkinlik tipleri (admin tarafından yönetilir)"""
    __tablename__ = "event_types"
    id         = Column(String(36), primary_key=True, default=_uuid)
    code       = Column(String(10), unique=True, nullable=False)   # 'yi', 'yd', 'ut', 'tk', 'dk'
    label      = Column(String(100), nullable=False)
    active     = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0)

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "code":       self.code,
            "label":      self.label,
            "active":     self.active,
            "sort_order": self.sort_order,
        }


class User(Base):
    """Kullanıcı modeli — admin / project_manager / e_dem"""
    __tablename__ = "users"

    id           = Column(String(36), primary_key=True, default=_uuid)
    email        = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role         = Column(String(32), nullable=False, default="project_manager")
    name         = Column(String(100), nullable=False)
    surname      = Column(String(100), nullable=False)
    title        = Column(String(100), default="")
    phone        = Column(String(30), default="")
    avatar_b64   = Column(Text, default="")          # profil fotoğrafı base64 (data URI)
    active       = Column(Boolean, default=True, nullable=False)
    created_at   = Column(DateTime, default=_now, nullable=False)
    org_title_id = Column(String(36), ForeignKey("org_titles.id"), nullable=True)

    # İlişkiler
    created_requests = relationship("Request", back_populates="creator", foreign_keys="Request.created_by")
    created_budgets  = relationship("Budget",  back_populates="creator", foreign_keys="Budget.created_by")
    org_title        = relationship("OrgTitle", back_populates="users")

    @property
    def full_name(self) -> str:
        return f"{self.name} {self.surname}".strip()

    @property
    def role_label(self) -> str:
        return USER_ROLE_LABELS.get(self.role, self.role)

    @property
    def initials(self) -> str:
        parts = [self.name[:1], self.surname[:1]]
        return "".join(p for p in parts if p).upper() or "?"

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "email":      self.email,
            "role":       self.role,
            "role_label": self.role_label,
            "name":       self.name,
            "surname":    self.surname,
            "full_name":  self.full_name,
            "title":      self.title,
            "phone":      self.phone,
            "active":     self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Venue(Base):
    """Tedarikçi / Mekan modeli"""
    __tablename__ = "venues"

    id            = Column(String(36), primary_key=True, default=_uuid)
    name          = Column(String(255), nullable=False)
    city          = Column(String(100), default="")        # birincil şehir
    cities_json   = Column(Text, default="[]")             # list[str] JSON
    supplier_type = Column(String(32), default="otel")
    address       = Column(Text, default="")
    stars         = Column(Integer, nullable=True)
    total_rooms   = Column(Integer, default=0)
    website       = Column(String(255), default="")
    notes         = Column(Text, default="")
    halls_json    = Column(Text, default="[]")             # list[Hall] JSON
    contacts_json = Column(Text, default="[]")             # list[Contact] JSON
    payment_term  = Column(String(100), default="")        # ödeme vadesi
    docs_json     = Column(Text, default="[]")             # list[{name, path}] yüklü belgeler
    active        = Column(Boolean, default=True, nullable=False)
    created_at    = Column(DateTime, default=_now, nullable=False)

    @property
    def docs_list(self) -> list:
        try:
            return json.loads(self.docs_json or "[]")
        except Exception:
            return []

    @property
    def cities(self) -> list:
        try:
            return json.loads(self.cities_json or "[]")
        except Exception:
            return []

    @cities.setter
    def cities(self, value: list) -> None:
        self.cities_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def halls(self) -> list:
        try:
            return json.loads(self.halls_json or "[]")
        except Exception:
            return []

    @halls.setter
    def halls(self, value: list) -> None:
        self.halls_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def contacts(self) -> list:
        try:
            return json.loads(self.contacts_json or "[]")
        except Exception:
            return []

    @contacts.setter
    def contacts(self, value: list) -> None:
        self.contacts_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def supplier_type_label(self) -> str:
        for st in SUPPLIER_TYPES:
            if st["value"] == self.supplier_type:
                return st["label"]
        return self.supplier_type

    @property
    def primary_contact(self) -> Optional[dict]:
        contacts = self.contacts
        return contacts[0] if contacts else None

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "name":           self.name,
            "city":           self.city,
            "cities":         self.cities,
            "supplier_type":  self.supplier_type,
            "supplier_type_label": self.supplier_type_label,
            "address":        self.address,
            "stars":          self.stars,
            "total_rooms":    self.total_rooms,
            "website":        self.website,
            "notes":          self.notes,
            "halls":          self.halls,
            "contacts":       self.contacts,
            "active":         self.active,
            "created_at":     self.created_at.isoformat() if self.created_at else None,
        }


class Customer(Base):
    """Müşteri / Firma modeli"""
    __tablename__ = "customers"

    id                  = Column(String(36), primary_key=True, default=_uuid)
    name                = Column(String(255), nullable=False)
    code                = Column(String(10), unique=True, nullable=False)   # 3 harfli küçük
    sector              = Column(String(100), default="")
    address             = Column(Text, default="")
    tax_office          = Column(String(100), default="")
    tax_number          = Column(String(30), default="")
    email               = Column(String(255), default="")
    phone               = Column(String(30), default="")
    notes               = Column(Text, default="")
    contacts_json       = Column(Text, default="[]")         # list[Contact] JSON
    payment_term        = Column(String(100), default="")    # ödeme vadesi
    docs_json           = Column(Text, default="[]")         # list[{name, path}] yüklü belgeler
    created_at          = Column(DateTime, default=_now, nullable=False)
    excel_template_path = Column(String(500), default="")   # yüklenen template dosya yolu
    excel_template_b64  = Column(Text, default="")          # template içeriği base64 (Railway kalıcılığı)
    excel_config_json   = Column(Text, default="{}")        # sütun mapping JSON

    # İlişkiler
    requests = relationship("Request", back_populates="customer")

    @property
    def contacts(self) -> list:
        try:
            return json.loads(self.contacts_json or "[]")
        except Exception:
            return []

    @contacts.setter
    def contacts(self, value: list) -> None:
        self.contacts_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def docs_list(self) -> list:
        try:
            return json.loads(self.docs_json or "[]")
        except Exception:
            return []

    @property
    def excel_config(self) -> dict:
        try:
            return json.loads(self.excel_config_json or "{}")
        except Exception:
            return {}

    @property
    def primary_contact(self):
        c = self.contacts
        return c[0] if c else None

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "name":       self.name,
            "code":       self.code,
            "sector":     self.sector,
            "address":    self.address,
            "tax_office": self.tax_office,
            "tax_number": self.tax_number,
            "email":      self.email,
            "phone":      self.phone,
            "notes":      self.notes,
            "contacts":   self.contacts,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Request(Base):
    """Etkinlik Talebi modeli"""
    __tablename__ = "requests"

    id               = Column(String(36), primary_key=True, default=_uuid)
    request_no       = Column(String(50), unique=True, nullable=False, index=True)
    client_name      = Column(String(255), nullable=False)
    customer_id      = Column(String(36), ForeignKey("customers.id"), nullable=True)
    event_name       = Column(String(255), nullable=False)
    event_type       = Column(String(32), default="toplanti")
    city             = Column(String(255), default="")
    cities_json      = Column(Text, default="[]")
    attendee_count   = Column(Integer, default=0)
    check_in         = Column(String(10), nullable=True)    # YYYY-MM-DD string
    check_out        = Column(String(10), nullable=True)
    accom_check_in   = Column(String(10), nullable=True)
    accom_check_out  = Column(String(10), nullable=True)
    quote_deadline   = Column(String(10), nullable=True)    # PM'in istediği teklif son tarihi
    status           = Column(String(32), default="draft", nullable=False)
    items_json       = Column(Text, default="{}")           # section → list[item] JSON
    description      = Column(Text, default="")
    notes            = Column(Text, default="")
    preferred_venues_json = Column(Text, default="[]")      # list[venue_id]
    selected_venues_json  = Column(Text, default="[]")      # list[venue_id]
    contact_person_json   = Column(Text, default="{}")      # selected contact info snapshot
    confirmed_at          = Column(DateTime, nullable=True)
    confirmed_budget_id   = Column(String(36), nullable=True)  # onaylanan bütçe id
    cancellation_reason   = Column(Text, default="")
    revision_count        = Column(Integer, default=0)
    created_by       = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at       = Column(DateTime, default=_now, nullable=False)
    updated_at       = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    # İlişkiler
    customer = relationship("Customer", back_populates="requests")
    creator  = relationship("User", back_populates="created_requests", foreign_keys=[created_by])
    budgets              = relationship("Budget", back_populates="request", cascade="all, delete-orphan")
    invoices             = relationship("Invoice", back_populates="request", order_by="Invoice.invoice_date",
                                        cascade="all, delete-orphan")
    expense_reports      = relationship("ExpenseReport", back_populates="request",
                                        cascade="all, delete-orphan",
                                        order_by="ExpenseReport.created_at")
    undocumented_entries = relationship("UndocumentedEntry", back_populates="request",
                                        cascade="all, delete-orphan",
                                        order_by="UndocumentedEntry.entry_date")

    @property
    def cities(self) -> list:
        try:
            return json.loads(self.cities_json or "[]")
        except Exception:
            return []

    @cities.setter
    def cities(self, value: list) -> None:
        self.cities_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def items(self) -> dict:
        try:
            return json.loads(self.items_json or "{}")
        except Exception:
            return {}

    @items.setter
    def items(self, value: dict) -> None:
        self.items_json = json.dumps(value or {}, ensure_ascii=False)

    @property
    def preferred_venues(self) -> list:
        try:
            return json.loads(self.preferred_venues_json or "[]")
        except Exception:
            return []

    @preferred_venues.setter
    def preferred_venues(self, value: list) -> None:
        self.preferred_venues_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def selected_venues(self) -> list:
        try:
            return json.loads(self.selected_venues_json or "[]")
        except Exception:
            return []

    @selected_venues.setter
    def selected_venues(self, value: list) -> None:
        self.selected_venues_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def contact_person(self) -> dict:
        try:
            return json.loads(self.contact_person_json or "{}")
        except Exception:
            return {}

    @property
    def status_label(self) -> str:
        return REQUEST_STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self) -> str:
        return REQUEST_STATUS_COLORS.get(self.status, "secondary")

    @property
    def event_type_label(self) -> str:
        # event_type now stores the code (yi/yd/ut/tk/dk) — label is looked up at runtime
        return self.event_type

    @property
    def cities_display(self) -> str:
        cities = self.cities
        if cities:
            return ", ".join(cities)
        return self.city or ""

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "request_no":       self.request_no,
            "client_name":      self.client_name,
            "customer_id":      self.customer_id,
            "event_name":       self.event_name,
            "event_type":       self.event_type,
            "event_type_label": self.event_type_label,
            "city":             self.city,
            "cities":           self.cities,
            "cities_display":   self.cities_display,
            "attendee_count":   self.attendee_count,
            "check_in":         self.check_in,
            "check_out":        self.check_out,
            "accom_check_in":   self.accom_check_in,
            "accom_check_out":  self.accom_check_out,
            "status":           self.status,
            "status_label":     self.status_label,
            "status_color":     self.status_color,
            "items":            self.items,
            "description":      self.description,
            "notes":            self.notes,
            "preferred_venues":  self.preferred_venues,
            "selected_venues":   self.selected_venues,
            "contact_person":    self.contact_person,
            "created_by":        self.created_by,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
            "updated_at":       self.updated_at.isoformat() if self.updated_at else None,
        }


class Budget(Base):
    """Bütçe modeli"""
    __tablename__ = "budgets"

    id                   = Column(String(36), primary_key=True, default=_uuid)
    request_id           = Column(String(36), ForeignKey("requests.id"), nullable=False)
    venue_name           = Column(String(255), default="")
    venue_id             = Column(String(36), nullable=True)   # Venue.id bağlantısı (isteğe bağlı)
    rows_json            = Column(Text, default="[]")     # list[BudgetRow] JSON
    created_by           = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at           = Column(DateTime, default=_now, nullable=False)
    updated_at           = Column(DateTime, default=_now, onupdate=_now, nullable=False)
    budget_status        = Column(String(32), default="draft_edem", nullable=False)
    revision_notes       = Column(Text, default="")   # manager → E-dem notları
    manager_notes        = Column(Text, default="")   # manager iç notları
    service_fee_pct      = Column(Float, default=0.0) # manager girer
    offer_currency       = Column(String(3), default="TRY")   # teklif para birimi
    exchange_rates_json  = Column(Text, default="{}")          # {"EUR":40.5,"USD":35.0}
    price_history_json   = Column(Text, default="[]")          # fiyat revize geçmişi
    price_snapshots_json = Column(Text, default="[]")          # fiyat arşivi (tam satır kopyaları)

    # İlişkiler
    request = relationship("Request", back_populates="budgets")
    creator = relationship("User",    back_populates="created_budgets", foreign_keys=[created_by])

    @property
    def rows(self) -> list:
        try:
            return json.loads(self.rows_json or "[]")
        except Exception:
            return []

    @rows.setter
    def rows(self, value: list) -> None:
        self.rows_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def exchange_rates(self) -> dict:
        try:
            return json.loads(self.exchange_rates_json or "{}")
        except Exception:
            return {}

    @property
    def price_history(self) -> list:
        try:
            return json.loads(self.price_history_json or "[]")
        except Exception:
            return []

    @property
    def price_snapshots(self) -> list:
        try:
            return json.loads(self.price_snapshots_json or "[]")
        except Exception:
            return []

    def rate_to_try(self, currency: str) -> float:
        """Verilen para biriminin TRY karşılığı (1 birim = X TRY)"""
        if not currency or currency == "TRY":
            return 1.0
        return float(self.exchange_rates.get(currency, 1.0) or 1.0)

    def amount_to_try(self, amount: float, currency: str) -> float:
        return amount * self.rate_to_try(currency)

    @property
    def grand_cost(self) -> float:
        """KDV dahil toplam maliyet — TRY cinsinden"""
        total = 0.0
        for row in self.rows:
            if row.get("is_service_fee") or row.get("is_accommodation_tax"):
                continue
            qty    = float(row.get("qty", 1) or 1)
            nights = float(row.get("nights", 1) or 1)
            cost   = float(row.get("cost_price", 0) or 0)
            vat    = float(row.get("vat_rate", 0) or 0)
            cur    = row.get("currency", "TRY") or "TRY"
            subtotal = self.amount_to_try(cost * qty * nights, cur)
            total += subtotal * (1 + vat / 100)
        return round(total, 2)

    @property
    def grand_sale(self) -> float:
        """KDV dahil toplam satış — TRY cinsinden"""
        total = 0.0
        for row in self.rows:
            qty    = float(row.get("qty", 1) or 1)
            nights = float(row.get("nights", 1) or 1)
            sale   = float(row.get("sale_price", 0) or 0)
            vat    = float(row.get("vat_rate", 0) or 0)
            cur    = row.get("currency", "TRY") or "TRY"
            subtotal = self.amount_to_try(sale * qty * nights, cur)
            total += subtotal * (1 + vat / 100)
        return round(total, 2)

    @property
    def grand_cost_excl_vat(self) -> float:
        """KDV hariç toplam maliyet — TRY cinsinden"""
        total = 0.0
        for row in self.rows:
            if row.get("is_service_fee") or row.get("is_accommodation_tax"):
                continue
            qty    = float(row.get("qty", 1) or 1)
            nights = float(row.get("nights", 1) or 1)
            cost   = float(row.get("cost_price", 0) or 0)
            cur    = row.get("currency", "TRY") or "TRY"
            total += self.amount_to_try(cost * qty * nights, cur)
        return round(total, 2)

    @property
    def grand_sale_excl_vat(self) -> float:
        """KDV hariç toplam satış — TRY cinsinden"""
        total = 0.0
        for row in self.rows:
            qty    = float(row.get("qty", 1) or 1)
            nights = float(row.get("nights", 1) or 1)
            sale   = float(row.get("sale_price", 0) or 0)
            cur    = row.get("currency", "TRY") or "TRY"
            total += self.amount_to_try(sale * qty * nights, cur)
        return round(total, 2)

    @property
    def grand_sale_offer(self) -> float:
        """KDV dahil toplam satış — offer_currency cinsinden"""
        oc = self.offer_currency or "TRY"
        if oc == "TRY":
            return self.grand_sale
        offer_rate = self.rate_to_try(oc)
        return round(self.grand_sale / offer_rate, 2) if offer_rate else self.grand_sale

    def to_dict(self) -> dict:
        return {
            "id":                  self.id,
            "request_id":          self.request_id,
            "venue_name":          self.venue_name,
            "rows":                self.rows,
            "grand_cost":          self.grand_cost,
            "grand_sale":          self.grand_sale,
            "grand_sale_offer":    self.grand_sale_offer,
            "offer_currency":      self.offer_currency or "TRY",
            "exchange_rates":      self.exchange_rates,
            "created_by":          self.created_by,
            "created_at":          self.created_at.isoformat() if self.created_at else None,
            "updated_at":          self.updated_at.isoformat() if self.updated_at else None,
        }


class Service(Base):
    """Hizmet Kataloğu"""
    __tablename__ = "services"

    id          = Column(String(36), primary_key=True, default=_uuid)
    category    = Column(String(64), nullable=False)
    name        = Column(String(255), nullable=False)
    unit        = Column(String(50), default="Adet")
    description = Column(Text, default="")
    active      = Column(Boolean, default=True, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "category":    self.category,
            "name":        self.name,
            "unit":        self.unit,
            "description": self.description,
            "active":      self.active,
        }


class CustomCategory(Base):
    """Admin tarafından oluşturulan özel kategoriler"""
    __tablename__ = "custom_categories"

    id        = Column(String(36), primary_key=True, default=_uuid)
    name      = Column(String(100), nullable=False)
    icon      = Column(String(10), default="📋")
    bg_color  = Column(String(10), default="#e0f2fe")
    txt_color = Column(String(10), default="#0c4a6e")

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "name":      self.name,
            "icon":      self.icon,
            "bg_color":  self.bg_color,
            "txt_color": self.txt_color,
        }


class EmailTemplate(Base):
    """Admin tarafından yönetilen e-posta şablonları"""
    __tablename__ = "email_templates"

    id          = Column(String(36), primary_key=True, default=_uuid)
    slug        = Column(String(64), unique=True, nullable=False)   # rfq | confirm_venue | cancel_venue | ...
    name        = Column(String(200), nullable=False)
    description = Column(String(400), default="")
    subject_tpl = Column(String(400), nullable=False)               # {event_name}, {request_no}, ...
    body_tpl    = Column(Text, nullable=False)                       # plain text, {variable} placeholders
    active      = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, default=_now, nullable=False)
    updated_at  = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    def render(self, ctx: dict) -> tuple[str, str]:
        """subject, body döner — eksik key'lerde boş string"""
        class _Safe(dict):
            def __missing__(self, key):
                return f"{{{key}}}"
        safe = _Safe(ctx)
        return self.subject_tpl.format_map(safe), self.body_tpl.format_map(safe)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "slug":        self.slug,
            "name":        self.name,
            "description": self.description,
            "subject_tpl": self.subject_tpl,
            "body_tpl":    self.body_tpl,
            "active":      self.active,
        }


# E-posta şablonu değişken referansı (UI'da gösterilir)
EMAIL_TEMPLATE_VARS = [
    {"key": "event_name",      "label": "Etkinlik Adı"},
    {"key": "request_no",      "label": "Referans No"},
    {"key": "client_name",     "label": "Müşteri Adı"},
    {"key": "check_in",        "label": "Etkinlik Başlangıç Tarihi"},
    {"key": "check_out",       "label": "Etkinlik Bitiş Tarihi"},
    {"key": "accom_check_in",  "label": "Konaklama Giriş Tarihi"},
    {"key": "accom_check_out", "label": "Konaklama Çıkış Tarihi"},
    {"key": "attendee_count",  "label": "Katılımcı Sayısı"},
    {"key": "venue_name",      "label": "Mekan / Tedarikçi Adı"},
    {"key": "contact_name",    "label": "Kontak Kişi Adı"},
    {"key": "quote_deadline",  "label": "Teklif Son Tarihi"},
    {"key": "company_name",    "label": "Şirket Adı"},
    {"key": "company_email",   "label": "Şirket E-posta"},
    {"key": "company_phone",   "label": "Şirket Telefonu"},
    {"key": "email_signature", "label": "E-posta İmzası"},
]

# Varsayılan şablon içerikleri (seed için)
_EMAIL_TEMPLATE_DEFAULTS = [
    {
        "slug": "rfq",
        "name": "RFQ — Tedarikçiye Fiyat Teklifi Talebi",
        "description": "Tedarikçilere gönderilen fiyat teklifi talep e-postası konu satırı.",
        "subject_tpl": "{event_name} — Fiyat Teklifi Talebi / {request_no}",
        "body_tpl": (
            "Sayın {contact_name},\n\n"
            "{client_name} adına organize ettiğimiz {event_name} etkinliği için fiyat teklifinizi talep etmekteyiz.\n\n"
            "Referans No : {request_no}\n"
            "Tarihler    : {check_in} – {check_out}\n"
            "Katılımcı   : {attendee_count} kişi\n\n"
            "Detaylı talep listesi aşağıda yer almaktadır. Son teklif tarihi: {quote_deadline}\n\n"
            "{email_signature}"
        ),
    },
    {
        "slug": "confirm_venue",
        "name": "Konfirme Bildirimi — Seçilen Mekan",
        "description": "Müşteri onayı sonrasında seçilen venue'ya gönderilen konfirme e-postası.",
        "subject_tpl": "{event_name} — Konfirme Bildirimi / {request_no}",
        "body_tpl": (
            "Sayın {contact_name},\n\n"
            "{event_name} etkinliğimiz için hazırladığınız teklif değerlendirmemiz tamamlanmış olup "
            "mekanınız / hizmetiniz konfirme edilmiştir.\n\n"
            "Referans No  : {request_no}\n"
            "Etkinlik     : {event_name}\n"
            "Müşteri      : {client_name}\n"
            "Tarihler     : {check_in} – {check_out}\n"
            "Katılımcı    : {attendee_count} kişi\n\n"
            "Kesin maliyet fiyatlarınızı en kısa sürede iletmenizi rica ederiz.\n\n"
            "{email_signature}"
        ),
    },
    {
        "slug": "cancel_venue",
        "name": "İptal Bildirimi — Seçilmeyen Mekan",
        "description": "Konfirme veya iptal sonrasında seçilmeyen venue'lara gönderilen teşekkür / iptal e-postası.",
        "subject_tpl": "{event_name} — Teklif Talebi İptali / {request_no}",
        "body_tpl": (
            "Sayın {contact_name},\n\n"
            "{event_name} etkinliğimiz kapsamında {venue_name} için tarafınıza ilettiğimiz "
            "teklif talebini iptal etmek durumunda kaldık.\n\n"
            "Referans No  : {request_no}\n"
            "Etkinlik     : {event_name}\n"
            "Tarihler     : {check_in} – {check_out}\n\n"
            "Gösterdiğiniz ilgi ve hazırladığınız teklif için teşekkür eder, "
            "ilerleyen projelerde tekrar bir araya gelmeyi umuyoruz.\n\n"
            "{email_signature}"
        ),
    },
    {
        "slug": "offer_customer",
        "name": "Müşteriye Teklif Gönderimi",
        "description": "Müşteriye Excel teklif dosyası gönderilirken açılan e-posta şablonu.",
        "subject_tpl": "Etkinlik Teklifi: {event_name} — {request_no}",
        "body_tpl": (
            "Sayın {contact_name},\n\n"
            "{event_name} etkinliğiniz için hazırlanan teklif dosyasını ekte sunmaktayız.\n\n"
            "Referans No: {request_no}\n"
            "Müşteri    : {client_name}\n"
            "Tarihler   : {check_in} – {check_out}\n\n"
            "Teklifi inceleyip dönüş yapmanızı rica ederiz.\n\n"
            "{email_signature}"
        ),
    },
    {
        "slug": "budget_to_manager",
        "name": "Bütçe Hazır — Manager Bildirimi",
        "description": "E-dem bütçeyi manager'a gönderdiğinde oluşturulan bildirim e-postası.",
        "subject_tpl": "Yeni Bütçe Hazır: {request_no} — {event_name}",
        "body_tpl": (
            "Merhaba,\n\n"
            "{request_no} referans numaralı {event_name} talebi için bütçe hazırlanmıştır. "
            "İnceleyip fiyatlandırma yapmanızı rica ederiz.\n\n"
            "Müşteri  : {client_name}\n"
            "Tarihler : {check_in} – {check_out}\n\n"
            "{email_signature}"
        ),
    },
    {
        "slug": "new_user_welcome",
        "name": "Yeni Kullanıcı — Hoşgeldin",
        "description": "Sisteme yeni eklenen kullanıcıya gönderilen hoşgeldin e-postası.",
        "subject_tpl": "{company_name} — Hesabınız Oluşturuldu",
        "body_tpl": (
            "Merhaba,\n\n"
            "{company_name} etkinlik yönetim sistemine hoş geldiniz. "
            "Hesabınız oluşturulmuştur.\n\n"
            "Sisteme giriş yaparak çalışmaya başlayabilirsiniz.\n\n"
            "{email_signature}"
        ),
    },
]


class Invoice(Base):
    """Fatura modeli — kesilen/gelen/komisyon/iade"""
    __tablename__ = "invoices"

    id            = Column(String(36), primary_key=True, default=_uuid)
    request_id    = Column(String(36), ForeignKey("requests.id"), nullable=False, index=True)
    invoice_type  = Column(String(32), nullable=False)   # kesilen|gelen|komisyon|iade_kesilen|iade_gelen
    invoice_no    = Column(String(100), default="")
    invoice_date  = Column(String(10), nullable=True)    # YYYY-MM-DD string
    due_date      = Column(String(10), nullable=True)    # YYYY-MM-DD string
    vendor_name   = Column(String(255), default="")      # tedarikçi/müşteri adı
    description   = Column(Text, default="")
    amount        = Column(Float, default=0.0)           # KDV hariç toplam, TRY (lines'dan hesaplanır)
    vat_rate      = Column(Float, default=20.0)          # geriye uyumluluk için (artık lines'da)
    vat_amount    = Column(Float, default=0.0)           # KDV tutarı toplamı
    total_amount  = Column(Float, default=0.0)           # KDV dahil toplam
    lines_json    = Column(Text, default="[]")           # list[{description, amount, vat_rate, vat_amount}]
    document_path    = Column(String(500), nullable=True)   # disk path (relative)
    document_name    = Column(String(255), nullable=True)   # orijinal dosya adı
    status           = Column(String(16), default="pending") # pending|approved|rejected|cancelled
    rejection_note   = Column(String(300), default="")
    approved_by      = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at      = Column(DateTime, nullable=True)
    created_by       = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at       = Column(DateTime, default=_now, nullable=False)
    updated_at       = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    request  = relationship("Request", back_populates="invoices")
    creator  = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])

    @property
    def lines(self) -> list:
        try:
            return json.loads(self.lines_json or "[]")
        except Exception:
            return []

    @property
    def type_label(self) -> str:
        return INVOICE_TYPE_LABELS.get(self.invoice_type, self.invoice_type)

    @property
    def is_income(self) -> bool:
        """Gelir etkisi pozitif mi? kesilen + komisyon = gelir; iade_gelen = maliyet azaltır"""
        return self.invoice_type in ("kesilen", "iade_gelen", "komisyon")

    @property
    def is_cost(self) -> bool:
        """Maliyet etkisi var mı? komisyon maliyet değil, gelirdir."""
        return self.invoice_type in ("gelen", "iade_kesilen")

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "request_id":    self.request_id,
            "invoice_type":  self.invoice_type,
            "type_label":    self.type_label,
            "invoice_no":    self.invoice_no,
            "invoice_date":  self.invoice_date,
            "due_date":      self.due_date,
            "vendor_name":   self.vendor_name,
            "description":   self.description,
            "amount":        self.amount,
            "vat_rate":      self.vat_rate,
            "vat_amount":    self.vat_amount,
            "total_amount":  self.total_amount,
            "document_path": self.document_path,
            "document_name": self.document_name,
            "status":        self.status,
            "created_by":    self.created_by,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# HBF — Harcama Bildirim Formu
# ---------------------------------------------------------------------------

EXPENSE_PAYMENT_METHODS = [
    {"value": "kredi_karti", "label": "Kredi Kartı"},
    {"value": "nakit",       "label": "Nakit"},
]

EXPENSE_DOC_TYPES = [
    {"value": "fatura",    "label": "Fatura"},
    {"value": "fis",       "label": "Fiş"},
    {"value": "belgesiz",  "label": "Belgesiz"},
]

EXPENSE_STATUSES = [
    {"value": "draft",     "label": "Taslak",        "color": "secondary"},
    {"value": "submitted", "label": "Onay Bekliyor",  "color": "warning"},
    {"value": "approved",  "label": "Onaylandı",      "color": "success"},
    {"value": "rejected",  "label": "Reddedildi",     "color": "danger"},
]
EXPENSE_STATUS_LABELS = {s["value"]: s["label"] for s in EXPENSE_STATUSES}
EXPENSE_STATUS_COLORS = {s["value"]: s["color"] for s in EXPENSE_STATUSES}


class ExpenseReport(Base):
    """HBF — Harcama Bildirim Formu başlığı"""
    __tablename__ = "expense_reports"

    id               = Column(String(36), primary_key=True, default=_uuid)
    request_id       = Column(String(36), ForeignKey("requests.id"), nullable=False, index=True)
    request_ids_json = Column(Text, default="[]")   # JSON array of {id,request_no,event_name,client_name}
    title            = Column(String(300), default="")
    status           = Column(String(16), default="draft")   # draft|submitted|approved|rejected
    submitted_by     = Column(String(36), ForeignKey("users.id"), nullable=False)
    approved_by      = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at      = Column(DateTime, nullable=True)
    rejection_note   = Column(Text, default="")
    created_at       = Column(DateTime, default=_now, nullable=False)
    updated_at       = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    # İlişkiler
    request   = relationship("Request",  back_populates="expense_reports")
    submitter = relationship("User",  foreign_keys=[submitted_by])
    approver  = relationship("User",  foreign_keys=[approved_by])
    items     = relationship("ExpenseItem", back_populates="report",
                             cascade="all, delete-orphan",
                             order_by="ExpenseItem.item_date")

    @property
    def status_label(self) -> str:
        return EXPENSE_STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self) -> str:
        return EXPENSE_STATUS_COLORS.get(self.status, "secondary")

    @property
    def grand_total(self) -> float:
        return round(sum(i.total_amount for i in self.items), 2)

    @property
    def grand_excl_vat(self) -> float:
        return round(sum(i.amount for i in self.items), 2)

    @property
    def grand_vat(self) -> float:
        return round(sum(i.vat_amount for i in self.items), 2)


class ExpenseItem(Base):
    """HBF kalemi"""
    __tablename__ = "expense_items"

    id                  = Column(String(36), primary_key=True, default=_uuid)
    report_id           = Column(String(36), ForeignKey("expense_reports.id"), nullable=False, index=True)
    assigned_request_id = Column(String(36), ForeignKey("requests.id"), nullable=True)  # hangi ref'e atandı
    item_date           = Column(String(10), default="")    # YYYY-MM-DD
    description         = Column(String(300), default="")
    payment_method      = Column(String(16), default="nakit")   # kredi_karti | nakit
    document_type       = Column(String(16), default="fis")     # fatura | fis | belgesiz
    amount              = Column(Float, default=0.0)    # KDV hariç
    vat_rate            = Column(Float, default=0.0)    # 0 için belgesiz; 10, 20 vb.
    vat_amount          = Column(Float, default=0.0)
    total_amount        = Column(Float, default=0.0)    # KDV dahil
    document_path       = Column(String(500), nullable=True)
    document_name       = Column(String(255), nullable=True)
    sort_order          = Column(Integer, default=0)
    created_at          = Column(DateTime, default=_now, nullable=False)

    report = relationship("ExpenseReport", back_populates="items")

    @property
    def payment_label(self) -> str:
        return {"kredi_karti": "Kredi Kartı", "nakit": "Nakit"}.get(self.payment_method, self.payment_method)

    @property
    def doc_label(self) -> str:
        return {"fatura": "Fatura", "fis": "Fiş", "belgesiz": "Belgesiz"}.get(self.document_type, self.document_type)


# ---------------------------------------------------------------------------
# Belgesiz Gelir / Gider
# ---------------------------------------------------------------------------

class UndocumentedEntry(Base):
    """Belgesiz gelir veya gider kalemi (KDV'siz)"""
    __tablename__ = "undocumented_entries"

    id          = Column(String(36), primary_key=True, default=_uuid)
    request_id  = Column(String(36), ForeignKey("requests.id"), nullable=False, index=True)
    entry_type  = Column(String(8), nullable=False)    # gelir | gider
    description = Column(String(300), default="")
    amount      = Column(Float, default=0.0)           # KDV yoktur
    entry_date  = Column(String(10), default="")       # YYYY-MM-DD
    created_by  = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at  = Column(DateTime, default=_now, nullable=False)

    request = relationship("Request", back_populates="undocumented_entries")
    creator = relationship("User", foreign_keys=[created_by])


class Settings(Base):
    """Sistem ayarları — tek satır (id=1)"""
    __tablename__ = "settings"

    id              = Column(Integer, primary_key=True, default=1)
    company_name    = Column(String(200), default="E-dem Etkinlik Yönetimi")
    company_address = Column(Text, default="")
    company_phone   = Column(String(50), default="")
    company_email   = Column(String(200), default="")
    logo_url        = Column(String(500), default="")
    email_signature = Column(Text, default="")
    rfq_subject_tpl = Column(String(300),
                             default="{event_name} Fiyat Teklifi - {request_no}")
    currency        = Column(String(10), default="₺")
    updated_at      = Column(DateTime, default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "company_name":    self.company_name,
            "company_address": self.company_address,
            "company_phone":   self.company_phone,
            "company_email":   self.company_email,
            "logo_url":        self.logo_url,
            "email_signature": self.email_signature,
            "rfq_subject_tpl": self.rfq_subject_tpl,
            "currency":        self.currency,
        }
