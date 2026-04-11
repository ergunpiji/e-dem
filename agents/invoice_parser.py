"""
Kural Tabanlı Türkiye Fatura Ayrıştırıcı (API'siz)
---------------------------------------------------
pdfplumber ile PDF metnini ve tablolarını çıkarır;
regex ile Türkçe fatura alanlarını ayrıştırır.

Desteklenen formatlar:
  - GIB e-Fatura / e-Arşiv (metin tabanlı PDF)
  - Logo, SAP, Mikro, Luca vb. muhasebe yazılımı çıktıları
  - Konaklama faturası (otel, pansiyon)

Desteklenmiyor:
  - Taranmış/görsel PDF, JPG, PNG (OCR gerektirir)
"""

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Türkçe ay isimleri
# ---------------------------------------------------------------------------
_TR_MONTHS = {
    "ocak": "01", "şubat": "02", "mart": "03", "nisan": "04",
    "mayıs": "05", "haziran": "06", "temmuz": "07", "ağustos": "08",
    "eylül": "09", "ekim": "10", "kasım": "11", "aralık": "12",
}

# Geçerli KDV oranları
_VALID_VAT = {0, 1, 8, 10, 18, 20}


def _snap_vat(v: int) -> int:
    if v in _VALID_VAT:
        return v
    return min(_VALID_VAT, key=lambda x: abs(x - v))


# ---------------------------------------------------------------------------
# Yardımcı: sayıyı float'a çevir (Türkçe format: 1.234,56 → 1234.56)
# ---------------------------------------------------------------------------
def _to_float(s: str) -> float:
    s = s.strip().replace(" ", "").replace("₺", "").replace("TL", "").replace("TRY", "")
    # 1.234,56 → 1234.56
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Tarih ayrıştırma → YYYY-MM-DD
# ---------------------------------------------------------------------------
def _parse_date(text: str) -> str:
    # "11.04.2026" veya "11/04/2026"
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", text)
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    # "11 Nisan 2026"
    m = re.search(
        r"\b(\d{1,2})\s+(ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)\s+(\d{4})\b",
        text, re.IGNORECASE
    )
    if m:
        d, mo_name, y = m.group(1), m.group(2).lower(), m.group(3)
        mo = _TR_MONTHS.get(mo_name, "01")
        return f"{y}-{mo}-{d.zfill(2)}"
    return ""


# ---------------------------------------------------------------------------
# Fatura no ayrıştırma
# ---------------------------------------------------------------------------
def _parse_invoice_no(text: str) -> str:
    patterns = [
        # e-Fatura ETTN UUID
        r"ETTN[:\s]*([A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12})",
        # "Fatura No : ABC2024000001"
        r"(?:Fatura\s*No|FATURA\s*NO|Fiş\s*No|Belge\s*No|Makbuz\s*No)[:\s#]*([A-Z0-9/_\-]{4,30})",
        # Seri + Sıra numarası
        r"(?:Seri|SERİ)[:\s]*([A-Z]{1,3})\s*(?:Sıra|No|SIRA)[:\s]*([0-9]{1,10})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return " ".join(g for g in m.groups() if g).strip()
    # Son çare: rakamlardan oluşan uzun numara
    m = re.search(r"\b(\d{10,})\b", text)
    if m:
        return m.group(1)
    return ""


# ---------------------------------------------------------------------------
# Firma adı
# ---------------------------------------------------------------------------
def _parse_vendor(lines: list[str]) -> str:
    """İlk 30 satırda firma unvanı sat içeren satırı bul."""
    keywords = ["a.ş.", "ltd.", "şti.", "a.ş", "a.s.", "inc.", "gmbh", "llc", "s.a.",
                "ticaret", "sanayi", "turizm", "holding", "grup", "group", "oteli",
                "otel", "restoran", "restaurant", "hotel"]
    # "Sayın", "Alıcı" sonrasındaki satır
    for i, ln in enumerate(lines[:40]):
        if re.search(r"(sayın|alici|alıcı|satıcı|satici|firma|unvan)[:\s]", ln, re.IGNORECASE):
            candidate = ln.split(":", 1)[-1].strip() if ":" in ln else ""
            if len(candidate) > 3:
                return candidate
            # sonraki satır
            if i + 1 < len(lines):
                return lines[i + 1].strip()
    # Büyük harf firma adı ara (en az 2 kelime, tamamen büyük harf)
    for ln in lines[:30]:
        clean = ln.strip()
        words = clean.split()
        if (len(words) >= 2 and clean.isupper() and len(clean) > 6
                and not re.match(r"^(FATURA|E-FATURA|E-ARŞİV|TARİH|NO|KDV|TOPLAM|MATRAH)", clean)):
            return clean
    # keyword içeren satır
    for ln in lines[:40]:
        low = ln.lower()
        if any(k in low for k in keywords) and len(ln.strip()) > 5:
            return ln.strip()
    return ""


# ---------------------------------------------------------------------------
# KDV satırlarını çıkar
# ---------------------------------------------------------------------------
def _parse_vat_lines(text: str) -> list[dict]:
    """
    Metinde "% 10 KDV  1.234,56" gibi satırları yakala.
    Her farklı oran için bir satır döndür.
    """
    results = []
    seen_rates = set()

    # "KDV (%10)" veya "% 10 KDV" veya "%10 KDV Tutarı : 1234,56"
    patterns = [
        r"%\s*(\d{1,2})\s*(?:KDV|Kdv)[^\d]*?([\d.,]+)",
        r"(?:KDV|Kdv)[^\d%]*%\s*(\d{1,2})[^\d]*([\d.,]+)",
        r"(\d{1,2})\s*%\s*(?:KDV|Kdv)[^\d]*([\d.,]+)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            try:
                rate = int(m.group(1))
                amt  = _to_float(m.group(2))
            except (ValueError, IndexError):
                continue
            if rate > 20 or amt <= 0:
                continue
            rate = _snap_vat(rate)
            if rate not in seen_rates:
                seen_rates.add(rate)
                results.append({"rate": rate, "vat_amount": amt})

    return results


# ---------------------------------------------------------------------------
# Toplam / matrah satırları
# ---------------------------------------------------------------------------
def _find_amount(text: str, labels: list[str]) -> float:
    for label in labels:
        pattern = rf"(?:{label})[^\d\-]*([\d.,]+)"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            v = _to_float(m.group(1))
            if v > 0:
                return v
    return 0.0


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------
def parse_pdf(file_bytes: bytes) -> dict:
    """
    PDF baytlarından fatura verisi çıkar.

    Returns:
        {
          "invoice_no": str,
          "invoice_date": str,     # YYYY-MM-DD
          "due_date": str,
          "vendor_name": str,
          "description": str,
          "lines": [{"description": str, "amount": float, "vat_rate": int, "vat_amount": float}],
          "_parse_method": "pdf_rules"
        }

    Raises:
        ValueError: PDF okunamıyorsa veya metin çıkarılamıyorsa
    """
    try:
        import pdfplumber
    except ImportError:
        raise ValueError("pdfplumber kurulu değil. requirements.txt'e ekleyin.")

    import io
    text_pages = []
    all_lines  = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        if not pdf.pages:
            raise ValueError("PDF sayfası bulunamadı.")

        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_pages.append(page_text)
            all_lines.extend(page_text.splitlines())

    full_text = "\n".join(text_pages)

    if len(full_text.strip()) < 30:
        raise ValueError(
            "PDF'den metin çıkarılamadı. Bu büyük olasılıkla taranmış/görsel bir PDF. "
            "AI analizi kullanın veya bilgileri manuel girin."
        )

    # ── Temel alanlar ──────────────────────────────────────────────────────
    invoice_no   = _parse_invoice_no(full_text)
    invoice_date = _parse_date(full_text)
    vendor_name  = _parse_vendor(all_lines)

    # Vade tarihi — "Son Ödeme", "Vade", "Due Date" sonrası tarih
    due_date = ""
    for label in [r"vade\s*(?:tarihi)?", r"son\s*ödeme", r"due\s*date"]:
        m = re.search(label + r"[:\s]*(\d{1,2}[./]\d{1,2}[./]\d{4})", full_text, re.IGNORECASE)
        if m:
            due_date = _parse_date(m.group(1))
            break

    # Genel açıklama — "Açıklama", "Konu", "Sipariş No"
    description = ""
    for label in [r"açıklama[:\s]+", r"konu[:\s]+", r"sipariş\s*no[:\s]+"]:
        m = re.search(label + r"(.{3,80})", full_text, re.IGNORECASE)
        if m:
            description = m.group(1).strip()[:100]
            break

    # ── Matrah ve KDV ─────────────────────────────────────────────────────
    # Genel toplam (KDV dahil)
    grand_total = _find_amount(full_text, [
        r"genel\s*toplam", r"ödenecek\s*tutar", r"toplam\s*tutar",
        r"grand\s*total", r"total\s*amount",
    ])

    # Matrah (KDV hariç)
    total_excl = _find_amount(full_text, [
        r"(?:toplam\s*)?matrah", r"kdv\s*hariç\s*tutar", r"net\s*tutar",
        r"ara\s*toplam",
    ])

    # KDV satırları (orana göre)
    vat_lines = _parse_vat_lines(full_text)

    # ── Kalemleri oluştur ─────────────────────────────────────────────────
    lines = []

    if vat_lines:
        # Her KDV oranı için bir satır
        for vl in vat_lines:
            rate       = vl["rate"]
            vat_amount = vl["vat_amount"]
            # Matrahı vat_amount'tan hesapla: matrah = vat_amount / (rate/100)
            if rate > 0:
                amount = round(vat_amount / (rate / 100), 2)
            else:
                # %0 satırı — matrahı toplam - diğerlerinden bul
                other_excl = sum(
                    round(v["vat_amount"] / (v["rate"] / 100), 2)
                    for v in vat_lines if v["rate"] > 0
                )
                amount = round((total_excl or grand_total) - other_excl, 2) if (total_excl or grand_total) else 0.0

            desc = "Konaklama Vergisi" if rate == 0 and _is_accommodation(full_text) else f"Hizmet / Mal (%{rate} KDV)"

            lines.append({
                "description": desc,
                "amount":      max(amount, 0.0),
                "vat_rate":    rate,
                "vat_amount":  vat_amount,
            })
    elif total_excl > 0:
        # Tek KDV oranı var ama satır bulunamadı — genel toplam varsa oran çıkar
        vat_total = (grand_total - total_excl) if grand_total > total_excl else 0.0
        rate = 0
        if total_excl > 0 and vat_total > 0:
            raw_rate = round(vat_total / total_excl * 100)
            rate = _snap_vat(raw_rate)
        lines.append({
            "description": "Hizmet / Mal",
            "amount":      total_excl,
            "vat_rate":    rate,
            "vat_amount":  round(vat_total, 2),
        })
    elif grand_total > 0:
        # Hiçbir şey bulunamadı — toplam bilinen tek şey
        lines.append({
            "description": "Hizmet / Mal",
            "amount":      grand_total,
            "vat_rate":    20,
            "vat_amount":  0.0,
        })

    # Konaklama Vergisi ayrı satırı ekle
    if _is_accommodation(full_text) and not any("Konaklama Vergisi" in l["description"] for l in lines):
        kv_amount = _find_amount(full_text, [r"konaklama\s*vergi"])
        if kv_amount > 0:
            lines.append({
                "description": "Konaklama Vergisi",
                "amount":      kv_amount,
                "vat_rate":    0,
                "vat_amount":  0.0,
            })

    return {
        "invoice_no":   invoice_no,
        "invoice_date": invoice_date,
        "due_date":     due_date,
        "vendor_name":  vendor_name,
        "description":  description,
        "lines":        lines,
        "_parse_method": "pdf_rules",
    }


def _is_accommodation(text: str) -> bool:
    keywords = ["konaklama", "geceleme", "gece", "oda", "check-in", "check in",
                "otel", "hotel", "pansiyon", "suit", "suite", "room"]
    low = text.lower()
    return sum(1 for k in keywords if k in low) >= 2
