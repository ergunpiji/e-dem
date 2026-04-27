"""
Merkezi Jinja2Templates örneği — tüm router'lar bu modülden import eder.
Böylece app.py'de tanımlanan özel filter'lar her yerde çalışır.
"""

import json
from datetime import datetime
from typing import Any, Union
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def format_date_tr(value: Any) -> str:
    """YYYY-MM-DD → GG.AA.YYYY"""
    if not value:
        return "—"
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%d.%m.%Y")
        # ISO formatındaki stringleri parse etmeye çalış (örn: "2023-10-27")
        dt = datetime.fromisoformat(str(value).split()[0])
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return str(value)


def format_money(value: Any) -> str:
    if value is None:
        return "₺0,00"
    try:
        # Eğer değer string ve virgüllü ise noktaya çevir (örn: "15,50" -> 15.50)
        if isinstance(value, str):
            value = value.replace(".", "").replace(",", ".")
        amount = float(value)
        return f"₺{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "₺0,00"


def role_label(role: str) -> str:
    labels = {
        "admin":           "Sistem Yöneticisi",
        "mudur":           "Müdür",
        "yonetici":        "Proje Yöneticisi",
        "asistan":         "Proje Asistanı",
        "project_manager": "Proje Yöneticisi",   # geriye uyumluluk
        "e_dem":           "E-dem (Satın Alma)",
        "muhasebe_muduru": "Muhasebe Müdürü",
        "muhasebe":        "Muhasebe Yetkilisi",
    }
    return labels.get(role, role)


def fromjson_filter(value: Any) -> Any:
    """JSON string → Python object (Jinja2 filter)"""
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value or {}
    except Exception:
        return {}


def format_datetime_tr(value: Any) -> str:
    """datetime veya ISO string → GG.AA.YYYY SS:DD"""
    if not value:
        return "—"
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%d.%m.%Y %H:%M")
        s = str(value)[:16].replace("T", " ")   # "2026-04-20T14:30" → "2026-04-20 14:30"
        dt = datetime.fromisoformat(s)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)[:16]


def tojson_filter(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


templates.env.filters["date_tr"]      = format_date_tr
templates.env.filters["datetime_tr"]  = format_datetime_tr
templates.env.filters["money"]        = format_money
templates.env.filters["role_label"]   = role_label
templates.env.filters["fromjson"]     = fromjson_filter
templates.env.filters["tojson"]       = tojson_filter


def module_enabled(request, module_key: str) -> bool:
    """Modül flag'ini template'lerden kontrol eder.
    Kullanım: {% if module_enabled(request, 'einvoice') %}...{% endif %}"""
    if request is None:
        return False
    enabled = getattr(request.state, "enabled_modules", None) or set()
    return module_key in enabled


templates.env.globals["module_enabled"] = module_enabled


# --- Şirket profili (SystemSetting'tan) ---

# Cache: her request'te DB'ye gitmemek için runtime cache (admin formu yazınca temizlenir)
_company_settings_cache: dict[str, str] = {}
_company_cache_loaded = False


def _load_company_settings() -> dict:
    """SystemSetting 'company_*' anahtarlarını cache'e yükle."""
    global _company_cache_loaded
    if _company_cache_loaded:
        return _company_settings_cache
    try:
        from database import SessionLocal
        from models import SystemSetting
        db = SessionLocal()
        try:
            rows = db.query(SystemSetting).filter(
                SystemSetting.key.like("company_%")
            ).all()
            _company_settings_cache.clear()
            for r in rows:
                _company_settings_cache[r.key] = r.value or ""
            _company_cache_loaded = True
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        pass
    return _company_settings_cache


def invalidate_company_cache() -> None:
    """Şirket profili güncellendikten sonra cache'i temizle."""
    global _company_cache_loaded
    _company_cache_loaded = False
    _company_settings_cache.clear()


def company(key: str, default: str = "") -> str:
    """Template global: {{ company('name', 'Prizmatik') }}"""
    settings = _load_company_settings()
    full_key = f"company_{key}" if not key.startswith("company_") else key
    val = settings.get(full_key, "") or ""
    # logo_path için dosya gerçekten var mı kontrol et — yoksa fallback'e düş.
    # (Örn. Railway ephemeral disk restart'ta uploads klasörü sıfırlanır.)
    if full_key == "company_logo_path" and val:
        try:
            import os
            rel = val.lstrip("/")
            base = os.path.dirname(os.path.abspath(__file__))
            abs_path = os.path.join(base, rel)
            if not os.path.isfile(abs_path):
                return default
        except Exception:  # noqa: BLE001
            return default
    return val or default


templates.env.globals["company"] = company
