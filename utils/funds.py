"""Fon havuzu (FundTransfer) yardımcı fonksiyonları.

- Bakiye hesaplama
- Güncel kur (TCMB)
- Şirket genelinde fon ana faturalarını ciro'dan filtrelemek için ID kümesi
"""
from typing import TYPE_CHECKING
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from models import Request as ReqModel


FUND_ADMIN_ROLES = {"admin", "muhasebe_muduru"}


def can_manage_funds(user) -> bool:
    """Fon havuzu aç / transfer yap yetkisi."""
    if not user:
        return False
    if user.role in FUND_ADMIN_ROLES:
        return True
    try:
        return bool(user.is_gm)
    except Exception:
        return False


def get_fund_balance(fund_req: "ReqModel", db: Session) -> dict:
    """Fon havuzu bakiyesi — original currency (KDV dahil).

    initial + in − out = remaining.
    """
    from models import FundTransfer
    transfers = db.query(FundTransfer).filter(
        FundTransfer.fund_request_id == fund_req.id
    ).all()
    total_out = round(sum(t.amount for t in transfers if t.direction == "out"), 2)
    total_in  = round(sum(t.amount for t in transfers if t.direction == "in"),  2)
    initial   = float(fund_req.fund_initial_amount or 0)
    remaining = round(initial - total_out + total_in, 2)
    return {
        "currency":       fund_req.fund_currency or "TRY",
        "vat_rate":       float(fund_req.fund_initial_vat_rate or 0),
        "initial":        initial,
        "initial_excl":   round(initial / (1 + float(fund_req.fund_initial_vat_rate or 0) / 100.0), 2)
                          if fund_req.fund_initial_vat_rate else initial,
        "out_total":      total_out,
        "in_total":       total_in,
        "remaining":      remaining,
        "transfer_count": len(transfers),
        "transfers":      transfers,
    }


def get_current_exchange_rate(currency: str) -> float:
    """Currency → TRY kuru. TRY için 1.0. TCMB başarısız olursa 1.0."""
    cur = (currency or "TRY").upper()
    if cur == "TRY":
        return 1.0
    try:
        from utils.tcmb import fetch_today_rates
        rates = fetch_today_rates()
        rate = rates.get(cur)
        if rate and rate > 0:
            return float(rate)
    except Exception:
        pass
    return 1.0


def fund_pool_invoice_ids(db: Session) -> set[str]:
    """Fon havuzu ana referanslarına bağlı 'kesilen' fatura ID'leri.

    Şirket geneli ciro/kar hesaplamalarında bu faturalar `.notin_()` ile
    filtrelenmelidir; yoksa fon faturası + transferler çift sayılır.
    """
    from models import Invoice, Request as ReqModel
    rows = (db.query(Invoice.id)
              .join(ReqModel, ReqModel.id == Invoice.request_id)
              .filter(ReqModel.is_fund_pool == True,        # noqa: E712
                      Invoice.invoice_type == "kesilen")
              .all())
    return {r[0] for r in rows}


def get_customer_fund_pools(customer_id: str, db: Session) -> list:
    """Müşteriye ait aktif fon havuzu referansları (alt ref dropdown için)."""
    from models import Request as ReqModel
    if not customer_id:
        return []
    return (db.query(ReqModel)
              .filter(ReqModel.customer_id == customer_id,
                      ReqModel.is_fund_pool == True,        # noqa: E712
                      ReqModel.status == "fund_pool")
              .order_by(ReqModel.created_at.desc())
              .all())
