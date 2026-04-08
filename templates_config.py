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
        "admin": "Admin",
        "project_manager": "Proje Yöneticisi",
        "e_dem": "E-dem (Satın Alma)",
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


templates.env.filters["date_tr"]   = format_date_tr
templates.env.filters["money"]     = format_money
templates.env.filters["role_label"] = role_label
templates.env.filters["fromjson"]  = fromjson_filter
