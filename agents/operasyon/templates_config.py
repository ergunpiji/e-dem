"""
Paylaşılan Jinja2Templates örneği.
Tüm router'lar buradan import eder — filtreler ve global'ler tek yerden yönetilir.
"""
import json
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def _from_json(s):
    if not s:
        return []
    try:
        result = json.loads(s)
        return result if isinstance(result, list) else []
    except Exception:
        return []


templates.env.filters["from_json"] = _from_json
