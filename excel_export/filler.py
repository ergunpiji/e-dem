"""
Müşteri Excel template'ini cell_map ile doldurur.

customer.excel_config_json'da saklanan cell_map yapısı:
{
  "vat_mode": "exclusive" | "inclusive",
  "header": {
      "B3": "event_name",
      "C4": "ref_no",
      ...
  },
  "data_block": {
      "start_row": 9,
      "end_anchor_text": "ARA TOPLAM",   // veya "end_row": 20
      "sheet": "Sheet1",                 // opsiyonel
      "columns": {
          "B": "service_name",
          "C": "notes",
          "D": "nights",
          "E": "qty",
          "F": "sale_price_eur",
          "H": "sale_price",
          "J": "total_incl"
      },
      "section_header_col": "B"          // opsiyonel
  }
}
"""
from __future__ import annotations

import io
import os

try:
    import openpyxl
    from openpyxl.utils import column_index_from_string
    OPENPYXL_OK = True
except ImportError:
    OPENPYXL_OK = False

from .builder import SECTION_LABELS, SECTIONS_ORDER


# ── Header alan çözücüleri ─────────────────────────────────────────────────────
def _header_resolvers(budget, request, customer, creator) -> dict:
    req = request

    def _date(d):
        if not d:
            return ""
        if isinstance(d, str):
            try:
                from datetime import date as _date_cls
                d = _date_cls.fromisoformat(d[:10])
            except Exception:
                return d
        return d.strftime("%d.%m.%Y")

    cities = ""
    if req:
        cities = (", ".join(req.cities)
                  if getattr(req, "cities", None)
                  else getattr(req, "city", ""))

    return {
        "event_name":     (getattr(req, "event_name", None)  or budget.venue_name or ""),
        "ref_no":         (getattr(req, "request_no", None)  or ""),
        "check_in":       _date(getattr(req, "check_in", None)),
        "check_out":      _date(getattr(req, "check_out", None)),
        "venue_name":     (budget.venue_name or ""),
        "customer_name":  (getattr(customer, "name", None)
                           or getattr(req, "client_name", None)
                           or ""),
        "creator_name":   (f"{getattr(creator, 'name', '')} "
                           f"{getattr(creator, 'surname', '')}".strip()
                           if creator else ""),
        "eur_rate":       budget.rate_to_try("EUR"),
        "usd_rate":       budget.rate_to_try("USD"),
        "attendee_count": (getattr(req, "attendee_count", None) or ""),
        "city":           cities,
    }


# ── Satır alan çözücüleri ──────────────────────────────────────────────────────
def _row_value(field: str, row: dict, budget, currency: str) -> float | str:
    """Tek bir bütçe satırı için istenen alanı döndürür."""
    qty    = float(row.get("qty",    1) or 1)
    nights = float(row.get("nights", 1) or 1)
    sale   = float(row.get("sale_price", 0) or 0)
    vat    = float(row.get("vat_rate",   0) or 0)

    # Para birimi dönüşümü
    row_cur = (row.get("currency") or "TRY").upper()
    if row_cur != currency:
        row_rate   = budget.rate_to_try(row_cur) or 1.0
        offer_rate = budget.rate_to_try(currency) or 1.0
        sale = sale * row_rate / offer_rate

    def _to_cur(target: str) -> float:
        try_val = float(row.get("sale_price", 0) or 0) * (budget.rate_to_try(row_cur) or 1.0)
        t_rate  = budget.rate_to_try(target) or 1.0
        return try_val / t_rate

    match field:
        case "service_name":   return row.get("service_name", "")
        case "notes":          return row.get("notes", "")
        case "unit":           return row.get("unit", "Adet")
        case "qty":            return qty
        case "nights":         return nights
        case "vat_rate":       return vat
        case "vat_pct":        return vat / 100
        case "sale_price":     return round(sale, 2)
        case "sale_price_inc": return round(sale * (1 + vat / 100), 2)
        case "total_excl":     return round(sale * qty * nights, 2)
        case "total_incl":     return round(sale * (1 + vat / 100) * qty * nights, 2)
        case "sale_price_eur": return round(_to_cur("EUR"), 2)
        case "sale_price_usd": return round(_to_cur("USD"), 2)
        case "total_eur":      return round(_to_cur("EUR") * qty * nights, 2)
        case "total_usd":      return round(_to_cur("USD") * qty * nights, 2)
        case _:                return ""


# ── Ana fonksiyon ──────────────────────────────────────────────────────────────
def fill_customer_template(
    template_path: str,
    cell_map: dict,
    budget,
    request,
    customer,
    creator,
) -> io.BytesIO:
    """
    Müşteri template'ini verilen cell_map ile doldurur.
    Dosyayı BytesIO olarak döndürür.
    """
    if not OPENPYXL_OK:
        raise RuntimeError("openpyxl kurulu değil")
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template bulunamadı: {template_path}")

    wb = openpyxl.load_workbook(template_path)

    # Sayfa seçimi
    sheet_name = (cell_map.get("data_block") or {}).get("sheet")
    ws = (wb[sheet_name]
          if sheet_name and sheet_name in wb.sheetnames
          else wb.active)

    currency = (budget.offer_currency or "TRY").upper()

    # ── Header hücrelerini doldur ──────────────────────────────────────────────
    header_vals = _header_resolvers(budget, request, customer, creator)
    for cell_addr, field_name in (cell_map.get("header") or {}).items():
        val = header_vals.get(field_name)
        if val is not None:
            try:
                ws[cell_addr.upper()] = val
            except Exception:
                pass

    # ── Veri bloğu ────────────────────────────────────────────────────────────
    data_block = cell_map.get("data_block")
    if not data_block:
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    start_row   = int(data_block.get("start_row", 1))
    col_defs    = data_block.get("columns", {})      # {letter: field_name}
    sec_hdr_col = data_block.get("section_header_col")
    end_anchor  = data_block.get("end_anchor_text")

    # Bütçe satırlarını grupla
    rows_by_sec: dict[str, list] = {}
    service_fee = None
    for r in budget.rows:
        if r.get("is_service_fee"):
            service_fee = r
            continue
        sec = r.get("section", "other")
        rows_by_sec.setdefault(sec, []).append(r)

    # Düz satır listesi: (type, data) — 'section' başlıkları + 'row' verileri
    flat_rows: list[tuple] = []
    for sec in SECTIONS_ORDER:
        sec_rows = rows_by_sec.get(sec, [])
        if not sec_rows:
            continue
        if sec_hdr_col:
            flat_rows.append(("section", sec))
        flat_rows.extend(("row", r) for r in sec_rows)
    if service_fee:
        flat_rows.append(("row", service_fee))

    # Anchor satırını bul (boş satır eklemek için)
    anchor_row = None
    if end_anchor:
        for r_idx in range(start_row, ws.max_row + 1):
            for c_idx in range(1, ws.max_column + 1):
                val = ws.cell(row=r_idx, column=c_idx).value
                if val and isinstance(val, str) and end_anchor.lower() in val.lower():
                    anchor_row = r_idx
                    break
            if anchor_row:
                break

    # Gerekenden az satır varsa ekle
    needed = len(flat_rows)
    if anchor_row:
        available = anchor_row - start_row
        if needed > available:
            for _ in range(needed - available):
                ws.insert_rows(anchor_row)
                anchor_row += 1

    # Satırları yaz
    current_row = start_row
    for row_type, row_data in flat_rows:
        if row_type == "section" and sec_hdr_col:
            ci = column_index_from_string(sec_hdr_col.upper())
            ws.cell(row=current_row, column=ci,
                    value=SECTION_LABELS.get(row_data, row_data))
            current_row += 1
            continue

        for col_letter, field_name in col_defs.items():
            try:
                ci  = column_index_from_string(col_letter.upper())
                val = _row_value(field_name, row_data, budget, currency)
                ws.cell(row=current_row, column=ci, value=val)
            except Exception:
                pass
        current_row += 1

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def _fill_ws(ws, cell_map: dict, budget, request, customer, creator) -> None:
    """Mevcut bir worksheet'i cell_map ile doldurur (in-place)."""
    currency = (budget.offer_currency or "TRY").upper()

    header_vals = _header_resolvers(budget, request, customer, creator)
    for cell_addr, field_name in (cell_map.get("header") or {}).items():
        val = header_vals.get(field_name)
        if val is not None:
            try:
                ws[cell_addr.upper()] = val
            except Exception:
                pass

    data_block = cell_map.get("data_block")
    if not data_block:
        return

    start_row   = int(data_block.get("start_row", 1))
    col_defs    = data_block.get("columns", {})
    sec_hdr_col = data_block.get("section_header_col")
    end_anchor  = data_block.get("end_anchor_text")

    rows_by_sec: dict[str, list] = {}
    service_fee = None
    for r in budget.rows:
        if r.get("is_service_fee"):
            service_fee = r
            continue
        sec = r.get("section", "other")
        rows_by_sec.setdefault(sec, []).append(r)

    flat_rows: list[tuple] = []
    for sec in SECTIONS_ORDER:
        sec_rows = rows_by_sec.get(sec, [])
        if not sec_rows:
            continue
        if sec_hdr_col:
            flat_rows.append(("section", sec))
        flat_rows.extend(("row", r) for r in sec_rows)
    if service_fee:
        flat_rows.append(("row", service_fee))

    anchor_row = None
    if end_anchor:
        for r_idx in range(start_row, ws.max_row + 1):
            for c_idx in range(1, ws.max_column + 1):
                val = ws.cell(row=r_idx, column=c_idx).value
                if val and isinstance(val, str) and end_anchor.lower() in val.lower():
                    anchor_row = r_idx
                    break
            if anchor_row:
                break

    needed = len(flat_rows)
    if anchor_row:
        available = anchor_row - start_row
        if needed > available:
            for _ in range(needed - available):
                ws.insert_rows(anchor_row)
                anchor_row += 1

    current_row = start_row
    for row_type, row_data in flat_rows:
        if row_type == "section" and sec_hdr_col:
            ci = column_index_from_string(sec_hdr_col.upper())
            ws.cell(row=current_row, column=ci,
                    value=SECTION_LABELS.get(row_data, row_data))
            current_row += 1
            continue
        for col_letter, field_name in col_defs.items():
            try:
                ci  = column_index_from_string(col_letter.upper())
                val = _row_value(field_name, row_data, budget, currency)
                ws.cell(row=current_row, column=ci, value=val)
            except Exception:
                pass
        current_row += 1


def fill_customer_template_multi(
    template_path: str,
    cell_map: dict,
    entries: list,          # [{"budget":..., "request":..., "customer":..., "creator":...}]
) -> io.BytesIO:
    """
    Birden fazla bütçeyi tek dosyada, her biri ayrı sheet olarak doldurur.
    Her sheet template'in aktif sayfasının bir kopyasıdır.
    """
    if not OPENPYXL_OK:
        raise RuntimeError("openpyxl kurulu değil")
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template bulunamadı: {template_path}")

    sheet_name = (cell_map.get("data_block") or {}).get("sheet")
    used_titles: list[str] = []

    wb = openpyxl.load_workbook(template_path)
    src_ws = (wb[sheet_name]
              if sheet_name and sheet_name in wb.sheetnames
              else wb.active)
    src_name = src_ws.title

    for i, entry in enumerate(entries):
        b   = entry["budget"]
        req = entry.get("request")
        cus = entry.get("customer")
        cre = entry.get("creator")

        if i == 0:
            ws = src_ws
        else:
            ws = wb.copy_worksheet(src_ws)

        # Sheet adı: venue_name
        raw_title = (b.venue_name or f"Bütçe {i+1}")[:28].strip()
        title = raw_title
        suffix = 2
        while title in used_titles:
            title = f"{raw_title[:25]} {suffix}"
            suffix += 1
        used_titles.append(title)
        ws.title = title

        _fill_ws(ws, cell_map, b, req, cus, cre)

    # Kaynak sheet ilk entry ile doldu; eğer entries boşsa yine de kaydedilir
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
