"""
Türk e-fatura PDF parser — AI'sız, regex + pdfplumber ile.

Temel sorunların çözümü:
- Python upper() Türkçe i/İ/ı ayrımını korumaz → normalize() fonksiyonu kullanılır
- Konaklama Vergisi tablo "Diğer Vergiler" sütunu VEYA özet satırından alınır
- Kalem tutarı "Mal Hizmet Tutarı" (son sütun) olarak belirlenir
"""
from __future__ import annotations

import io
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Türkçe-güvenli string araçları
# ---------------------------------------------------------------------------

_TR_MAP = str.maketrans("İıĞğŞşÇçÖöÜü", "IiGgSsCcOoUu")

def _norm(s: str) -> str:
    """Türkçe karakterleri ASCII'ye çevirip büyük harfe al — karşılaştırma için."""
    return str(s or "").translate(_TR_MAP).upper()


def _tr_float(s) -> Optional[float]:
    """'1.234,56 TL' veya '122.704,15TL' → 1234.56"""
    s = str(s or "").strip()
    # TL, ₺, % işaretlerini temizle
    s = re.sub(r'[TLtl₺%=\s]', '', s)
    s = re.sub(r'[^0-9,.]', '', s)
    if not s:
        return None
    # Türk formatı: binlik=nokta, ondalık=virgül → 1.234,56
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        v = float(s)
        return v if v >= 0 else None
    except ValueError:
        return None


def _parse_date(s: str) -> Optional[str]:
    """DD-MM-YYYY veya DD.MM.YYYY → YYYY-MM-DD"""
    if not s:
        return None
    m = re.match(r'(\d{1,2})[-./](\d{1,2})[-./](\d{4})', s.strip())
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    m = re.match(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', s.strip())
    if m:
        return s.strip()[:10]
    return None


def _clean(s) -> str:
    return str(s or "").strip()


# ---------------------------------------------------------------------------
# Ana parser
# ---------------------------------------------------------------------------

def parse_invoice(file_bytes: bytes, filename: str = "invoice.pdf") -> dict:
    """
    PDF faturayı parse eder.

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

    all_text  = ""
    all_tables: list = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            all_text += (page.extract_text(x_tolerance=2, y_tolerance=2) or "") + "\n"
            for tbl in (page.extract_tables() or []):
                all_tables.append(tbl)

    # ── Fatura No ─────────────────────────────────────────────────────────────
    for pat in [
        r'Fatura No\s*[:\s]+([A-Z0-9]{5,30})',
        r'FATURA NO\s*[:\s]+([A-Z0-9]{5,30})',
    ]:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            result["invoice_no"] = _clean(m.group(1))
            break

    # ── Tarihler ──────────────────────────────────────────────────────────────
    for label, key in [
        ("Fatura Tarihi", "invoice_date"),
        ("Vade Tarihi",   "due_date"),
        ("Son Ödeme",     "due_date"),
    ]:
        m = re.search(rf'{re.escape(label)}\s*[:\s]+(\d{{1,2}}[-./]\d{{1,2}}[-./]\d{{4}})',
                      all_text, re.IGNORECASE)
        if m and not result[key]:
            result[key] = _parse_date(m.group(1))

    # ── Tedarikçi Adı ─────────────────────────────────────────────────────────
    result["vendor_name"] = _extract_vendor_name(all_text)

    # ── Para Birimi ───────────────────────────────────────────────────────────
    if re.search(r'\bEUR\b|€', all_text):
        result["currency"] = "EUR"
    elif re.search(r'\bUSD\b', all_text):
        result["currency"] = "USD"

    # ── Genel Toplam ──────────────────────────────────────────────────────────
    for pat in [
        r'Ödenecek Tutar[\s:]*([0-9.,]+)\s*TL',
        r'Vergiler Dahil Toplam Tutar[\s:]*([0-9.,]+)\s*TL',
        r'GENEL TOPLAM[\s:]*([0-9.,]+)',
    ]:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            v = _tr_float(m.group(1))
            if v and v > 0:
                result["grand_total_incl"] = v
                break

    # ── Kalem Satırları ───────────────────────────────────────────────────────
    result["lines"] = _extract_all_lines(all_text, all_tables)

    # ── Notlar ────────────────────────────────────────────────────────────────
    notes = [
        _clean(m.group(1))
        for m in re.finditer(r'Not:\s*(.+)', all_text, re.IGNORECASE)
        if not _clean(m.group(1)).upper().startswith("YALNIZ") and len(_clean(m.group(1))) > 3
    ]
    if notes:
        result["description"] = "; ".join(notes[:3])

    return result


# ---------------------------------------------------------------------------
# Tedarikçi adı
# ---------------------------------------------------------------------------

def _extract_vendor_name(text: str) -> Optional[str]:
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    sayin_idx = next(
        (i for i, l in enumerate(lines) if re.match(r'^SAYIN\b', l, re.IGNORECASE)),
        None,
    )
    skip = re.compile(
        r'Vergi Dairesi|Mersis|Phone|Fax|Mah\.|Cad\.|Sok\.|Posta Kodu|'
        r'^\+?\(?\d|e-FATURA|e-ARŞİV|ETTN|www\.|http',
        re.IGNORECASE,
    )
    rng = lines[:sayin_idx] if sayin_idx else lines[:8]
    for l in rng:
        if not skip.search(l) and len(l) > 5:
            return l
    return None


# ---------------------------------------------------------------------------
# Tüm kalemleri çıkar (tablo + konaklama vergisi)
# ---------------------------------------------------------------------------

def _extract_all_lines(text: str, tables: list) -> list:
    # Önce tablodan dene, sonra metinden
    lines = _extract_lines_from_tables(tables)
    if not lines:
        lines = _extract_lines_from_text(text)

    # Konaklama vergisini ayrı ekle
    kv = _extract_accommodation_tax(text, tables)
    if kv is not None:
        # Zaten eklenmemişse ekle
        already = any(_norm(l.get("description", "")).startswith("KONAKLAMA VERG")
                      for l in lines)
        if not already:
            lines.append({
                "description": "Konaklama Vergisi",
                "amount":      round(kv, 2),
                "vat_rate":    0,
            })
    return lines


# ---------------------------------------------------------------------------
# Konaklama vergisi tutarı
# ---------------------------------------------------------------------------

def _extract_accommodation_tax(text: str, tables: list) -> Optional[float]:
    """
    Konaklama vergisini bul. İki kaynağa sırayla bakar:
    1. Tablo 'Diğer Vergiler' sütunu
    2. Özet satırı: 'Hesaplanan KONAKLAMA VERGİSİ(% 2) 2.454,08TL'
    """
    # 1. Tablodan
    for tbl in tables:
        if not tbl or len(tbl) < 2:
            continue
        header_norm = [_norm(c) for c in (tbl[0] or [])]
        other_col = next(
            (i for i, h in enumerate(header_norm)
             if "DIGER VERGI" in h or "DIGER VERGİ" in h or "DIGER VERGI" in h),
            None,
        )
        if other_col is None:
            # "DİĞER" kalıbını da ara (normalize sonrası "DIGER" olur)
            other_col = next(
                (i for i, h in enumerate(header_norm) if "DIGER" in h),
                None,
            )
        if other_col is None:
            continue
        for row in tbl[1:]:
            if not row or other_col >= len(row):
                continue
            cell = _clean(row[other_col])
            if "KONAKLAMA" not in _norm(cell):
                continue
            # "KONAKLAMA VERGİSİ (%2,00)\n=2.454,08TL" → tutarı çek
            m = re.search(r'[=\s]([0-9.,]+)\s*TL', cell, re.IGNORECASE)
            if m:
                v = _tr_float(m.group(1))
                if v and v > 0:
                    return v

    # 2. Özet metinden: hem "(%2)" hem "(% 2)" formatını yakala
    for pat in [
        r'KONAKLAMA\s+VERG[İI]S[İI]\s*\(\s*%?\s*\d+[,.]?\d*\s*\)\s*([0-9.,]+)\s*TL',
        r'KONAKLAMA\s+VERG[İI]S[İI].*?([0-9.,]+)\s*TL',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            v = _tr_float(m.group(1))
            if v and v > 0:
                return v

    return None


# ---------------------------------------------------------------------------
# Tablo tabanlı kalem çıkarma
# ---------------------------------------------------------------------------

def _extract_lines_from_tables(tables: list) -> list:
    """
    pdfplumber tablosundan kalem satırlarını parse et.

    Sütun eşleştirmesi _norm() ile yapılır (Türkçe i/İ/ı sorununu önler).

    Türk e-fatura tablo sütunları (normalize edilmiş isimler):
      SIRA NO | MAL HIZMET | MIKTAR | BIRIM FIYAT | ISKONTO ORANI | ISKONTO TUTARI
      | KDV ORANI | KDV TUTARI | DIGER VERGILER | MAL HIZMET TUTARI
    """
    lines = []

    for tbl in tables:
        if not tbl or len(tbl) < 2:
            continue

        raw_header = tbl[0] or []
        header_norm = [_norm(c) for c in raw_header]

        # Kalem tablosu mu? "MAL" ve ("FIYAT" veya "TUTAR") içermeli
        has_desc  = any("MAL" in h or "HIZMET" in h or "ACIKLAMA" in h
                        for h in header_norm)
        has_price = any("FIYAT" in h or "TUTAR" in h or "BEDEL" in h
                        for h in header_norm)
        if not (has_desc and has_price):
            continue

        # Sütun indekslerini bul (normalize karşılaştırma)
        desc_col   = _col(header_norm, ["MAL HIZMET", "HIZMET ADI", "ACIKLAMA", "MAL/HIZMET"])
        # "Mal Hizmet Tutarı" = son fiyat sütunu (birim fiyattan farklı, iskonto/kdv sonrası)
        amt_col    = _col(header_norm, ["MAL HIZMET TUTARI", "HIZMET TUTARI", "TUTAR"])
        birim_col  = _col(header_norm, ["BIRIM FIYAT", "BIRIM"])
        kdv_col    = _col(header_norm, ["KDV ORANI", "KDV %"])
        other_col  = _col(header_norm, ["DIGER VERGI", "DIGER"])

        # Fallback: desc 2. sütun, amt son sütun
        if desc_col is None:
            desc_col = 1
        if amt_col is None:
            amt_col = len(raw_header) - 1  # son sütun

        for row in tbl[1:]:
            if not row:
                continue
            desc = _clean(row[desc_col]) if desc_col < len(row) else ""
            if not desc:
                continue
            # Toplam/iskonto/başlık satırlarını atla
            if re.search(r'TOPLAM|GENEL|ISKONTO|YALNIZ|SIRA NO|MAL HIZMET$',
                         _norm(desc)):
                continue

            # ── Tutar (Mal Hizmet Tutarı — son sütun) ──────────────────────
            amount = None
            if amt_col < len(row):
                amount = _tr_float(row[amt_col])
            # amt_col'dan alınamazsa en sağdan geri doğru sayısal hücre ara
            # (ama "Diğer Vergiler" hücresini atla)
            if not amount:
                for i in range(len(row) - 1, -1, -1):
                    if other_col is not None and i == other_col:
                        continue
                    v = _tr_float(row[i])
                    if v and v > 0:
                        amount = v
                        break

            # ── KDV Oranı ──────────────────────────────────────────────────
            vat_rate = 20  # varsayılan
            if kdv_col is not None and kdv_col < len(row):
                raw = _clean(row[kdv_col])
                # "%10,00" veya "10" veya "%10" formatları
                raw_clean = re.sub(r'[^0-9,.]', '', raw).replace(',', '.')
                try:
                    vat_rate = int(float(raw_clean))
                except (ValueError, TypeError):
                    pass

            if desc and amount and amount > 0:
                lines.append({
                    "description": desc,
                    "amount":      round(amount, 2),
                    "vat_rate":    vat_rate,
                })

    return lines


def _col(header_norm: list, candidates: list) -> Optional[int]:
    """Normalize edilmiş header'da aday isimleri ara (kısmi eşleşme)."""
    for cand in candidates:
        cand_norm = _norm(cand)
        for i, h in enumerate(header_norm):
            if cand_norm in h:
                return i
    return None


# ---------------------------------------------------------------------------
# Metin tabanlı kalem çıkarma (tablo başarısız olursa fallback)
# ---------------------------------------------------------------------------

def _extract_lines_from_text(text: str) -> list:
    """
    Türk e-fatura satır formatından regex ile kalem çıkar.

    Tipik satır:
      1 KONAKLAMA 1Adet 122.704,15TL %0,00 0,00TL %10,00 12.270,42TL ... 122.704,15TL
      2 TOPLANTI BEDELİ 1Adet 147.581,01TL %0,00 0,00TL %20,00 29.516,20TL 147.581,01TL

    Strateji:
    - Satır no + açıklama + birim + birimFiyatTL → açıklamayı yakala
    - %XX[,XX] → KDV oranını yakala (iskonto %0'dan sonra gelen)
    - Satırdaki son NNNN,NNTL → Mal Hizmet Tutarı
    """
    lines = []

    # Her satırı normalize et (çok satırlı hücreleri birleştir için önce satır tabanlı çalış)
    # Sıra no ile başlayan satırları bul
    pattern = re.compile(
        r'^(\d{1,3})\s+'                              # 1. grup: sıra no
        r'([A-ZÇĞİÖŞÜa-zçğışöü][^\n\d]{1,60?}?)\s+' # 2. grup: açıklama (önce harf)
        r'\d[\d.]*\s*(?:Adet|adet|KG|Kg|Saat|saat|Gün|gün|Kişi|kişi|m2|M2)?\s*'  # miktar+birim
        r'[0-9.,]+\s*TL\s*'                           # birim fiyat
        r'%[0-9,]+\s+[0-9.,]+\s*TL\s*'               # iskonto oran + tutar
        r'%([0-9,]+)',                                 # 3. grup: KDV oranı
        re.MULTILINE,
    )

    # Son TL tutarını satırdan çeken yardımcı
    def last_tl_amount(line: str) -> Optional[float]:
        matches = re.findall(r'([0-9.,]+)\s*TL', line)
        for raw in reversed(matches):
            v = _tr_float(raw)
            if v and v > 100:  # 100 TL'den küçük değerler birim/vergi olabilir
                return v
        # 100 TL eşiği tutmazsa hepsine bak
        for raw in reversed(matches):
            v = _tr_float(raw)
            if v and v > 0:
                return v
        return None

    for m in pattern.finditer(text):
        desc = _clean(m.group(2))
        vat_raw = re.sub(r'[^0-9]', '', m.group(3).split(',')[0])
        try:
            vat_rate = int(vat_raw)
        except ValueError:
            vat_rate = 20

        # Satırın tamamını al (pattern başlangıcından satır sonuna kadar)
        line_start = m.start()
        line_end   = text.find('\n', m.end())
        full_line  = text[line_start: line_end if line_end > 0 else m.end() + 200]

        amount = last_tl_amount(full_line)

        if desc and amount and amount > 0:
            # Toplam/başlık satırı değil mi?
            if not re.search(r'TOPLAM|GENEL|ISKONTO', _norm(desc)):
                lines.append({
                    "description": desc,
                    "amount":      round(amount, 2),
                    "vat_rate":    vat_rate,
                })

    return lines
