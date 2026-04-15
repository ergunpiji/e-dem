"""
Operasyon Ajanı Konfigürasyonu.

Sub-app olarak E-dem'e mount edilince:
  OA_URL_PREFIX = "/operasyon"

Standalone çalışınca:
  OA_URL_PREFIX = "" (boş string, davranış değişmez)
"""
import os

URL_PREFIX: str = os.getenv("OA_URL_PREFIX", "")


def url(path: str) -> str:
    """Redirect URL'lerini prefix ile oluştur.

    Kullanım:
        from config import url
        return RedirectResponse(url=url("/events/123"))
    """
    return f"{URL_PREFIX}{path}"
