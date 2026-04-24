"""
Eski sistemden (e-dem) yeni sisteme (prizmafinans) fatura verisi aktarır.

Kullanım:
  OLD_DB="postgresql://..." NEW_DB="postgresql://..." python3 migrate_invoices.py

Opsiyonel:
  DRY_RUN=1   → veritabanına yazmaz, sadece rapor verir
  SKIP_DUPES=1 → aynı fatura_no + tarih varsa atlar (varsayılan: 1)
"""

import os, sys, json

try:
    import psycopg2, psycopg2.extras
except ImportError:
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    import psycopg2, psycopg2.extras

OLD_DB   = os.environ.get("OLD_DB", "").strip()
NEW_DB   = os.environ.get("NEW_DB", "").strip()
DRY_RUN  = os.environ.get("DRY_RUN", "0") == "1"
SKIP_DUP = os.environ.get("SKIP_DUPES", "1") == "1"

def fix(url):
    return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url

if not OLD_DB or not NEW_DB:
    print("HATA: OLD_DB ve NEW_DB env değişkenleri gerekli.")
    sys.exit(1)

OLD_DB, NEW_DB = fix(OLD_DB), fix(NEW_DB)

print("[1] Eski DB'ye bağlanılıyor...")
old_conn = psycopg2.connect(OLD_DB)
old_cur  = old_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("[2] Yeni DB'ye bağlanılıyor...")
new_conn = psycopg2.connect(NEW_DB)
new_cur  = new_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# ── Eski şemayı keşfet ────────────────────────────────────────────────────────
old_cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'invoices'
    ORDER BY ordinal_position
""")
old_cols = {r["column_name"]: r["data_type"] for r in old_cur.fetchall()}
print(f"\n[3] Eski 'invoices' tablosu sütunları: {list(old_cols.keys())}\n")

if not old_cols:
    print("HATA: Eski DB'de 'invoices' tablosu bulunamadı.")
    sys.exit(1)

# ── Eski vendor map (id → name) ───────────────────────────────────────────────
old_cur.execute("SELECT id, name FROM financial_vendors")
old_vendor_map = {r["id"]: (r["name"] or "").strip() for r in old_cur.fetchall()}

# ── Yeni vendor map (lower(name) → id) ───────────────────────────────────────
new_cur.execute("SELECT id, name FROM financial_vendors")
new_vendor_map = {(r["name"] or "").strip().lower(): r["id"] for r in new_cur.fetchall()}

# ── Eski reference map (id → ref_no) ─────────────────────────────────────────
old_ref_map = {}
try:
    old_cur.execute("SELECT id, ref_no FROM references ORDER BY id")
    old_ref_map = {r["id"]: (r["ref_no"] or "").strip() for r in old_cur.fetchall()}
except Exception:
    try:
        old_cur.execute('SELECT id, ref_no FROM "references" ORDER BY id')
        old_ref_map = {r["id"]: (r["ref_no"] or "").strip() for r in old_cur.fetchall()}
    except Exception as e:
        print(f"  [UYR] Eski referanslar okunamadı: {e}")

# ── Yeni reference map (ref_no → id) ─────────────────────────────────────────
new_cur.execute('SELECT id, ref_no FROM "references"')
new_ref_map = {(r["ref_no"] or "").strip().upper(): r["id"] for r in new_cur.fetchall()}

# ── Yeni admin user id ────────────────────────────────────────────────────────
new_cur.execute("SELECT id FROM users WHERE is_admin = TRUE ORDER BY id LIMIT 1")
admin_row = new_cur.fetchone()
admin_id  = admin_row["id"] if admin_row else None

# ── Mevcut fatura sayısı ──────────────────────────────────────────────────────
new_cur.execute("SELECT COUNT(*) AS cnt FROM invoices")
existing_count = new_cur.fetchone()["cnt"]
print(f"[4] Yeni DB'de mevcut fatura: {existing_count}")

# ── Eski faturaları çek ───────────────────────────────────────────────────────
old_cur.execute("SELECT * FROM invoices ORDER BY invoice_date, id")
rows = old_cur.fetchall()
print(f"[5] Eski DB'de {len(rows)} fatura bulundu.\n")

# ── Sütun adı fallback yardımcıları ──────────────────────────────────────────
def col(row, *names, default=None):
    for n in names:
        if n in row and row[n] is not None:
            return row[n]
    return default

# ── invoice_type normalizasyonu ───────────────────────────────────────────────
VALID_TYPES = {"gelen", "kesilen", "komisyon", "iade_gelen", "iade_kesilen"}
TYPE_MAP = {
    "incoming": "gelen", "outgoing": "kesilen", "commission": "komisyon",
    "incoming_refund": "iade_gelen", "outgoing_refund": "iade_kesilen",
    "in": "gelen", "out": "kesilen",
}

def normalize_type(v):
    if not v:
        return "gelen"
    v = str(v).lower().strip()
    if v in VALID_TYPES:
        return v
    return TYPE_MAP.get(v, "gelen")

# ── status normalizasyonu ─────────────────────────────────────────────────────
VALID_STATUS = {"draft", "approved", "paid", "cancelled"}

def normalize_status(v):
    if not v:
        return "approved"
    v = str(v).lower().strip()
    if v in VALID_STATUS:
        return v
    return "approved"

# ── payment_method normalizasyonu ─────────────────────────────────────────────
VALID_PM = {"nakit", "banka", "kredi_karti", "cek", "acik_hesap"}

def normalize_pm(v):
    if not v:
        return None
    v = str(v).lower().strip()
    if v in VALID_PM:
        return v
    mapping = {"cash": "nakit", "bank": "banka", "credit_card": "kredi_karti",
               "cheque": "cek", "check": "cek", "open": "acik_hesap"}
    return mapping.get(v, None)

# ── Aktarım ───────────────────────────────────────────────────────────────────
inserted = skipped = errors = 0

for row in rows:
    try:
        invoice_date = col(row, "invoice_date", "date", "created_at")
        if not invoice_date:
            print(f"  ATLA (tarih yok): id={row.get('id')}")
            skipped += 1
            continue

        invoice_no  = col(row, "invoice_no", "invoice_number", "invoice_num", "number", default="")
        amount      = float(col(row, "amount", "total_amount", "net_amount", default=0) or 0)
        vat_rate    = float(col(row, "vat_rate", "vat", default=0) or 0)
        currency    = col(row, "currency", default="TRY") or "TRY"
        notes       = col(row, "notes", "description", default="") or ""
        due_date    = col(row, "due_date", default=None)
        paid_at     = col(row, "paid_at", "payment_date", default=None)
        items_json  = col(row, "items_json", "items", default=None)

        inv_type  = normalize_type(col(row, "invoice_type", "type", "kind"))
        status    = normalize_status(col(row, "status"))
        pm        = normalize_pm(col(row, "payment_method"))

        # Vendor eşleştir
        old_vid = col(row, "vendor_id", "financial_vendor_id", default=None)
        new_vid = None
        if old_vid and old_vid in old_vendor_map:
            vname = old_vendor_map[old_vid].lower()
            new_vid = new_vendor_map.get(vname)
            if not new_vid:
                print(f"  [UYR] Tedarikçi eşleştirilemedi: '{old_vendor_map[old_vid]}' (fatura {row.get('id')})")

        # Reference eşleştir
        old_rid = col(row, "ref_id", "reference_id", "request_id", default=None)
        new_rid = None
        if old_rid and old_rid in old_ref_map:
            ref_no = old_ref_map[old_rid].upper()
            new_rid = new_ref_map.get(ref_no)

        # Duplicate kontrolü
        if SKIP_DUP and invoice_no:
            new_cur.execute(
                "SELECT id FROM invoices WHERE invoice_no = %s AND invoice_date = %s",
                (str(invoice_no).strip(), invoice_date)
            )
            if new_cur.fetchone():
                print(f"  ATLA (mevcut): {invoice_no} / {invoice_date}")
                skipped += 1
                continue

        if DRY_RUN:
            print(f"  DRY: {inv_type} | {invoice_no} | {invoice_date} | {amount} {currency} | vendor→{new_vid} | ref→{new_rid}")
            inserted += 1
            continue

        new_cur.execute("""
            INSERT INTO invoices
                (ref_id, vendor_id, invoice_type, invoice_no, invoice_date,
                 amount, vat_rate, currency, status, payment_method,
                 paid_at, due_date, items_json, notes, created_by, created_at)
            VALUES
                (%s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s, %s)
        """, (
            new_rid, new_vid, inv_type, str(invoice_no).strip() if invoice_no else "",
            invoice_date, amount, vat_rate, currency[:3], status, pm,
            paid_at, due_date, items_json, str(notes).strip(),
            admin_id, col(row, "created_at", default="NOW()")
        ))
        print(f"  EKLENDİ: {inv_type} | {invoice_no} | {invoice_date} | {amount:.2f} {currency}")
        inserted += 1

    except Exception as e:
        print(f"  HATA (id={row.get('id')}): {e}")
        errors += 1

if not DRY_RUN:
    new_conn.commit()
    print(f"\nTamamlandı: {inserted} eklendi, {skipped} atlandı, {errors} hata.")
else:
    print(f"\nDRY RUN tamamlandı: {inserted} işlenecekti, {skipped} atlanacaktı, {errors} hata.")

old_cur.close(); old_conn.close()
new_cur.close(); new_conn.close()
