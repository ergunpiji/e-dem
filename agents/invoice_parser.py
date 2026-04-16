"""
Türk e-fatura PDF parser — AI'sız, regex + pdfplumber ile.

Desteklenen format: standart Türk e-fatura / e-arşiv fatura PDF'leri.
"""
from __future__ import annotations

import io
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _tr_float(s: str) -> Optional[float]:
    """'1.234,56 TL' → 1234.56"""
    if not s:
        return None
    s = str(s).strip().rstrip("TL").rstrip("₺").strip()
    s = re.sub(r'[^0-9,.]', '', s)
    if not s:
        return None
    # Binlik nokta, ondalık virgül: 1.234,56 → 1234.56
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(s: str) -> Optional[str]:
    """DD-MM-YYYY veya DD.MM.YYYY → YYYY-MM-DD (HTML date input formatı)"""
    if not s:
        return None
    s = s.strip()
    m = re.match(r'(\d{1,2})[-./](\d{1,2})[-./](\d{4})', s)
    if m:
        d, mo, y = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
        return f"{y}-{mo}-{d}"
    m = re.match(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', s)
    if m:
        return s[:10]
    return None


def _clean(s) -> str:
    return str(s or "").strip()


# ---------------------------------------------------------------------------
# Ana parser
# ---------------------------------------------------------------------------

def parse_invoice(file_bytes: bytes, filename: str = "invoice.pdf") -> dict:
    """
    PDF faturayı parse eder, form alanlarını doldurur.

    Döndürülen dict:
        invoice_no, invoice_date, due_date, vendor_name,
        description, currency, grand_total_incl,
        lines: [{description, amount, vat_rate}]
    """
    try:
        import pdfplumber
    except ImportError:
        raise ValueError("pdfplumber kurulu değil.")

    result: dict = {
        "invoice_no":       None,
        "invoice_date":     None,
        "due_date":         None,
        "vendor_name":      None,
        "description":      None,
        "currency":         "TRY",
        "grand_total_incl": None,
        "lines":            [],
    }

    all_text = ""
    all_tables: list = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            all_text += page_text + "\n"
            for tbl in (page.extract_tables() or []):
                all_tables.append(tbl)

    # ── 1. Fatura No ──────────────────────────────────────────────────────────
    for pattern in [
        r'Fatura No[:\s]+([A-Z0-9]{6,30})',
        r'FATURA NO[:\s]+([A-Z0-9]{6,30})',
        r'No[:\s]+([A-Z]{1,4}\d{8,20})',          # HP02026000000119 gibi
    ]:
        m = re.search(pattern, all_text, re.IGNORECASE)
        if m:
            result["invoice_no"] = _clean(m.group(1))
            break

    # ── 2. Fatura Tarihi ─────────────────────────────────────────────────────
    for pattern in [
        r'Fatura Tarihi[:\s]+(\d{1,2}[-./]\d{1,2}[-./]\d{4})',
        r'FATURA TARİHİ[:\s]+(\d{1,2}[-./]\d{1,2}[-./]\d{4})',
    ]:
        m = re.search(pattern, all_text, re.IGNORECASE)
        if m:
            result["invoice_date"] = _parse_date(m.group(1))
            break

    # ── 3. Vade Tarihi ────────────────────────────────────────────────────────
    for pattern in [
        r'Vade Tarihi[:\s]+(\d{1,2}[-./]\d{1,2}[-./]\d{4})',
        r'Son Ödeme[:\s]+(\d{1,2}[-./]\d{1,2}[-./]\d{4})',
        r'İskonto Tarihi[:\s]+(\d{1,2}[-./]\d{1,2}[-./]\d{4})',
    ]:
        m = re.search(pattern, all_text, re.IGNORECASE)
        if m:
            result["due_date"] = _parse_date(m.group(1))
            break

    # ── 4. Tedarikçi Adı ──────────────────────────────────────────────────────
    vendor = _extract_vendor_name(all_text)
    if vendor:
        result["vendor_name"] = vendor

    # ── 5. Para Birimi ────────────────────────────────────────────────────────
    if re.search(r'\bEUR\b|€', all_text):
        result["currency"] = "EUR"
    elif re.search(r'\bUSD\b', all_text):
        result["currency"] = "USD"
    else:
        result["currency"] = "TRY"

    # ── 6. Genel Toplam ───────────────────────────────────────────────────────
    for pattern in [
        r'Ödenecek Tutar\s*[:\s]*([0-9.,]+)\s*TL',
        r'Vergiler Dahil Toplam Tutar\s*[:\s]*([0-9.,]+)\s*TL',
        r'GENEL TOPLAM\s*[:\s]*([0-9.,]+)',
        r'Toplam Tutar\s*[:\s]*([0-9.,]+)\s*TL',
    ]:
        m = re.search(pattern, all_text, re.IGNORECASE)
        if m:
            val = _tr_float(m.group(1))
            if val and val > 0:
                result["grand_total_incl"] = val
                break

    # ── 7. Kalem Satırları ────────────────────────────────────────────────────
    lines = _extract_lines(all_text, all_tables)
    if lines:
        result["lines"] = lines

    # ── 8. Açıklama / Notlar (Not: satırları) ────────────────────────────────
    notes = []
    for m in re.finditer(r'Not:\s*(.+)', all_text, re.IGNORECASE):
        note = _clean(m.group(1))
        if note and not note.upper().startswith("YALNIZ") and len(note) > 3:
            notes.append(note)
    if notes:
        result["description"] = "; ".join(notes[:3])

    return result


# ---------------------------------------------------------------------------
# Vendor name çıkarma
# ---------------------------------------------------------------------------

def _extract_vendor_name(text: str) -> Optional[str]:
    """
    Türk e-faturasında tedarikçi adı "SAYIN" bloğundan önce gelir.
    """
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # "SAYIN" satırını bul — ondan önceki satırlar tedarikçi alanı
    sayin_idx = None
    for i, l in enumerate(lines):
        if re.match(r'^SAYIN\b', l, re.IGNORECASE):
            sayin_idx = i
            break

    skip_re = re.compile(
        r'Vergi Dairesi|Mersis|Phone|Fax|Mah\.|Cad\.|Sok\.|Posta Kodu|'
        r'^\+?\(?\d|e-FATURA|e-ARŞİV|ETTN|www\.|http|ŞUBESİ$',
        re.IGNORECASE
    )

    candidates = []
    search_range = lines[:sayin_idx] if sayin_idx else lines[:8]
    for l in search_range:
        if skip_re.search(l):
            continue
        if len(l) > 5:
            candidates.append(l)

    if candidates:
        return candidates[0]
    return None


# ---------------------------------------------------------------------------
# Kalem satırları çıkarma
# ---------------------------------------------------------------------------

def _extract_lines(text: str, tables: list) -> list:
    """Tablolardan, başarısız olursa metinden kalem satırlarını çıkar."""
    lines = _extract_lines_from_tables(tables)
    if lines:
        return lines
    return _extract_lines_from_text(text)


def _extract_lines_from_tables(tables: list) -> list:
    """
    pdfplumber tablosundan kalem satırlarını parse et.
    Türk e-fatura tablo başlıkları tipik olarak:
      Sıra No | Mal Hizmet | Miktar | Birim Fiyat | İskonto | KDV Oranı | KDV Tutarı | ... | Mal Hizmet Tutarı
    """
    lines = []
    for tbl in tables:
        if not tbl or len(tbl) < 2:
            continue

        header = [_clean(c).upper() for c in (tbl[0] or [])]

        # Kalem tablosu mu?
        has_desc  = any(any(k in h for k in ["MAL", "HİZMET", "AÇIKLAMA"]) for h in header)
        has_price = any(any(k in h for k in ["FİYAT", "TUTAR", "BEDEL"]) for h in header)
        if not (has_desc and has_price):
            continue

        # Sütun indekslerini bul
        desc_col  = _find_col(header, ["MAL HİZMET", "HİZMET", "AÇIKLAMA", "MAL/HİZMET"])
        # Önce "MAL HİZMET TUTARI" ara, yoksa birim fiyat
        amt_col   = _find_col(header, ["MAL HİZMET TUTARI", "TUTAR", "BİRİM FİYAT", "BEDEL"])
        vat_col   = _find_col(header, ["KDV ORANI", "KDV %", "KDV ORANı"])

        if desc_col is None:
            desc_col = 1

        for row in tbl[1:]:
            if not row:
                continue
            desc = _clean(row[desc_col]) if desc_col < len(row) else ""
            if not desc:
                continue
            # Toplam/iskonto satırlarını atla
            if re.search(r'TOPLAM|GENEL|İSKONTO|YALNIZ', desc, re.I):
                continue
            # Sütun başlığı tekrarı
            if any(k in desc.upper() for k in ["MAL HİZMET", "AÇIKLAMA", "SIRA"]):
                continue

            # Tutar: önce belirlenen sütun, sonra son sayısal hücre
            amount = None
            if amt_col is not None and amt_col < len(row):
                amount = _tr_float(row[amt_col])
            if not amount:
                for cell in reversed(row):
                    v = _tr_float(cell)
                    if v and v > 0:
                        amount = v
                        break

            # KDV oranı
            vat_rate = 20
            if vat_col is not None and vat_col < len(row):
                raw = _clean(row[vat_col]).replace('%', '').replace(',', '.')
                try:
                    vat_rate = int(float(raw))
                except (ValueError, TypeError):
                    # Satırdaki %XX kalıbını metinden al
                    vm = re.search(r'%(\d{1,2})', _clean(row[vat_col]))
                    if vm:
                        vat_rate = int(vm.group(1))

            if desc and amount:
                lines.append({
                    "description": desc,
                    "amount":      round(amount, 2),
                    "vat_rate":    vat_rate,
                })

    return lines


def _find_col(header: list, candidates: list) -> Optional[int]:
    """Header'da aday isimleri ara (kısmi eşleşme)."""
    for cand in candidates:
        for i, h in enumerate(header):
            if cand in h:
                return i
    return None


def _extract_lines_from_text(text: str) -> list:
    """
    Tablo çıkarma başarısız olursa metin üzerinde regex.
    Türk e-fatura satır formatı:
      1  KONAKLAMA  1Adet  122.704,15TL  %0,00  0,00TL  %10,00  12.270,42TL  122.704,15TL
    """
    lines = []
    # Sıra numarası ile başlayan satırlar
    pattern = re.compile(
        r'^\s*(\d{1,3})\s+'
        r'([A-ZÇĞİÖŞÜa-zçğışöü][^\n]{2,60?}?)\s+'
        r'\d+\s*(?:Adet|adet|KG|Saat|gün|Gün|Kişi|kişi)?\s*'
        r'([0-9.,]+)\s*TL'
        r'(?:.*?%(\d{1,2}))?'
        r'.*?([0-9.,]+)\s*TL\s*$',
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        desc   = _clean(m.group(2))
        amount = _tr_float(m.group(5) or m.group(3))
        vat    = int(m.group(4)) if m.group(4) else 20
        if desc and amount and amount > 0:
            lines.append({
                "description": desc,
                "amount":      round(amount, 2),
                "vat_rate":    vat,
            })
    return lines
