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
    {"value": "admin",           "label": "Admin"},
    {"value": "project_manager", "label": "Proje Yöneticisi"},
    {"value": "e_dem",           "label": "E-dem (Satın Alma)"},
]

USER_ROLE_LABELS = {r["value"]: r["label"] for r in USER_ROLES}

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
    budgets  = relationship("Budget", back_populates="request", cascade="all, delete-orphan")

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
