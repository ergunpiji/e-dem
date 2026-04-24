"""
Eski sistemden (e-dem) yeni sisteme (prizmafinans) referans verisi aktarır.
Müşterileri de eşleştirir (code veya name üzerinden).

Kullanım:
  OLD_DB="postgresql://..." NEW_DB="postgresql://..." python3 migrate_references.py

Opsiyonel:
  DRY_RUN=1  → veritabanına yazmaz, sadece rapor verir
"""

import os, sys

try:
    import psycopg2, psycopg2.extras
except ImportError:
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    import psycopg2, psycopg2.extras

OLD_DB  = os.environ.get("OLD_DB", "").strip()
NEW_DB  = os.environ.get("NEW_DB", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

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

# ── Eski references şemasını keşfet ──────────────────────────────────────────
old_cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'references' ORDER BY ordinal_position
""")
old_cols = [r["column_name"] for r in old_cur.fetchall()]
print(f"\n[3] Eski 'references' sütunları: {old_cols}\n")

if not old_cols:
    # Eski sistemde tablo adı farklı olabilir (requests, events, vb.)
    old_cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' ORDER BY table_name
    """)
    tables = [r["table_name"] for r in old_cur.fetchall()]
    print(f"Eski DB tabloları: {tables}")
    print("HATA: 'references' tablosu bulunamadı. Tablo adını kontrol edin.")
    sys.exit(1)

# ── Eski customer map (id → {name, code}) ────────────────────────────────────
old_customer_map = {}
try:
    old_cur.execute("SELECT id, name, code FROM customers")
    for r in old_cur.fetchall():
        old_customer_map[r["id"]] = {"name": (r["name"] or "").strip(), "code": (r.get("code") or "").strip().lower()}
except Exception as e:
    print(f"  [UYR] Eski müşteriler okunamadı: {e}")

# ── Yeni customer map (code → id, lower(name) → id) ──────────────────────────
new_customer_by_code = {}
new_customer_by_name = {}
try:
    new_cur.execute("SELECT id, name, code FROM customers")
    for r in new_cur.fetchall():
        if r.get("code"):
            new_customer_by_code[r["code"].strip().lower()] = r["id"]
        new_customer_by_name[(r["name"] or "").strip().lower()] = r["id"]
except Exception as e:
    print(f"  [UYR] Yeni müşteriler okunamadı: {e}")

# ── Yeni DB'de mevcut ref_no'lar ─────────────────────────────────────────────
new_cur.execute('SELECT ref_no FROM "references"')
existing_ref_nos = {r["ref_no"].strip().upper() for r in new_cur.fetchall()}
print(f"[4] Yeni DB'de mevcut referans sayısı: {len(existing_ref_nos)}")

# ── Admin user id ─────────────────────────────────────────────────────────────
new_cur.execute("SELECT id FROM users WHERE is_admin = TRUE ORDER BY id LIMIT 1")
admin_row = new_cur.fetchone()
admin_id  = admin_row["id"] if admin_row else None

# ── event_type normalizasyonu ─────────────────────────────────────────────────
VALID_EVENT_TYPES = {"toplanti", "konferans", "gala", "egitim", "lansman", "diger"}
EVENT_MAP = {
    "meeting": "toplanti", "conference": "konferans", "training": "egitim",
    "launch": "lansman", "other": "diger", "toplantı": "toplanti",
    "eğitim": "egitim",
}

def normalize_event_type(v):
    if not v:
        return "diger"
    v = str(v).lower().strip()
    if v in VALID_EVENT_TYPES:
        return v
    return EVENT_MAP.get(v, "diger")

# ── status normalizasyonu ─────────────────────────────────────────────────────
def normalize_status(v):
    if not v:
        return "aktif"
    v = str(v).lower().strip()
    mapping = {
        "active": "aktif", "aktif": "aktif",
        "completed": "tamamlandi", "tamamlandi": "tamamlandi", "tamamlandı": "tamamlandi",
        "cancelled": "iptal", "canceled": "iptal", "iptal": "iptal",
        "closed": "tamamlandi", "done": "tamamlandi",
    }
    return mapping.get(v, "aktif")

def col(row, *names, default=None):
    for n in names:
        if n in row and row[n] is not None:
            return row[n]
    return default

# ── Eski referansları çek ─────────────────────────────────────────────────────
try:
    old_cur.execute('SELECT * FROM "references" ORDER BY created_at, id')
except Exception:
    old_cur.execute("SELECT * FROM references ORDER BY id")
rows = old_cur.fetchall()
print(f"[5] Eski DB'de {len(rows)} referans bulundu.\n")

inserted = skipped = errors = 0

for row in rows:
    try:
        ref_no = col(row, "ref_no", "reference_no", "code", "request_no", default="")
        if not ref_no:
            print(f"  ATLA (ref_no yok): id={row.get('id')}")
            skipped += 1
            continue

        ref_no = str(ref_no).strip().upper()

        # Zaten varsa atla
        if ref_no in existing_ref_nos:
            print(f"  ATLA (mevcut): {ref_no}")
            skipped += 1
            continue

        title = col(row, "title", "event_name", "name", "description", default=ref_no) or ref_no
        event_type = normalize_event_type(col(row, "event_type", "type", default=None))
        status     = normalize_status(col(row, "status", default=None))
        check_in   = col(row, "check_in", "start_date", "event_date", "date_from", default=None)
        check_out  = col(row, "check_out", "end_date", "date_to", default=None)
        notes      = col(row, "notes", "description", default="") or ""
        created_at = col(row, "created_at", default=None)

        # Müşteri eşleştir
        old_cid = col(row, "customer_id", "client_id", default=None)
        new_cid = None
        if old_cid and old_cid in old_customer_map:
            c = old_customer_map[old_cid]
            new_cid = new_customer_by_code.get(c["code"]) or new_customer_by_name.get(c["name"].lower())
            if not new_cid:
                print(f"  [UYR] Müşteri eşleştirilemedi: '{c['name']}' (ref {ref_no})")

        if DRY_RUN:
            print(f"  DRY: {ref_no} | {title[:40]} | {event_type} | {status} | {check_in} → {check_out} | müşteri→{new_cid}")
            inserted += 1
            existing_ref_nos.add(ref_no)
            continue

        new_cur.execute("""
            INSERT INTO references
                (ref_no, customer_id, title, event_type, check_in, check_out,
                 status, notes, created_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            ref_no, new_cid, str(title).strip()[:300], event_type,
            check_in, check_out, status, str(notes).strip(),
            admin_id, created_at
        ))
        existing_ref_nos.add(ref_no)
        print(f"  EKLENDİ: {ref_no} | {str(title).strip()[:50]}")
        inserted += 1

    except Exception as e:
        print(f"  HATA (id={row.get('id')}, ref_no={row.get('ref_no')}): {e}")
        errors += 1

if not DRY_RUN:
    new_conn.commit()
    print(f"\nTamamlandı: {inserted} eklendi, {skipped} atlandı, {errors} hata.")
else:
    print(f"\nDRY RUN tamamlandı: {inserted} işlenecekti, {skipped} atlanacaktı, {errors} hata.")

old_cur.close(); old_conn.close()
new_cur.close(); new_conn.close()
