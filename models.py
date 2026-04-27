"""
E-dem — Ön Muhasebe Sistemi
SQLAlchemy modelleri
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    surname = Column(String(120), nullable=True)
    title = Column(String(150), nullable=True)
    phone = Column(String(40), nullable=True)
    email = Column(String(200), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_approver = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Müşteri & Tedarikçi
# ---------------------------------------------------------------------------

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    code = Column(String(3), nullable=False, unique=True)
    sector = Column(String(100))
    tax_no = Column(String(20))
    tax_office = Column(String(100))
    address = Column(Text)
    email = Column(String(200))
    phone = Column(String(50))
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # E-Fatura mükellef sorgu cache'i
    is_efatura_user = Column(Boolean, nullable=True)
    efatura_alias = Column(String(100), nullable=True)
    efatura_checked_at = Column(DateTime, nullable=True)

    references = relationship("Reference", back_populates="customer")
    cheques = relationship("Cheque", back_populates="customer")


class FinancialVendor(Base):
    __tablename__ = "financial_vendors"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    vendor_type = Column(String(50))
    iban = Column(String(40))
    tax_no = Column(String(20))
    tax_office = Column(String(100))
    address = Column(Text)
    phone = Column(String(50))
    email = Column(String(200))
    payment_term = Column(Integer, default=30)
    contact = Column(String(200))
    location_type = Column(String(20), default="turkiye")
    cities = Column(Text)
    bank_accounts_json = Column(Text, nullable=True)
    notes = Column(Text)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # E-Fatura mükellef sorgu cache'i
    is_efatura_user = Column(Boolean, nullable=True)
    efatura_alias = Column(String(100), nullable=True)
    efatura_checked_at = Column(DateTime, nullable=True)

    invoices = relationship("Invoice", back_populates="vendor")
    cheques = relationship("Cheque", back_populates="vendor")
    general_expenses = relationship("GeneralExpense", back_populates="vendor")
    prepayments = relationship("VendorPrepayment", back_populates="vendor",
                               cascade="all, delete-orphan", order_by="VendorPrepayment.payment_date")


# ---------------------------------------------------------------------------
# Kasa & Banka & Kredi Kartı
# ---------------------------------------------------------------------------

class CashBook(Base):
    __tablename__ = "cash_books"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    currency = Column(String(3), default="TRY", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    entries = relationship("CashEntry", back_populates="book", cascade="all, delete-orphan")
    day_closes = relationship("CashDayClose", back_populates="book", cascade="all, delete-orphan")


class CashDayClose(Base):
    """Gün sonu kapanış kaydı — kapalı günlere artık işlem yapılamaz."""
    __tablename__ = "cash_day_closes"

    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("cash_books.id"), nullable=False)
    close_date = Column(Date, nullable=False)
    opening_balance = Column(Float, nullable=False, default=0.0)
    closing_balance = Column(Float, nullable=False)
    physical_count = Column(Float, nullable=False)
    difference = Column(Float, nullable=False, default=0.0)
    notes = Column(String(300), nullable=True)
    closed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    closed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    book = relationship("CashBook", back_populates="day_closes")
    closer = relationship("User", foreign_keys=[closed_by])


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    bank_name = Column(String(100))
    iban = Column(String(40))
    currency = Column(String(3), default="TRY", nullable=False)
    opening_balance = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    movements = relationship("BankMovement", back_populates="account", cascade="all, delete-orphan")
    salary_payments = relationship("SalaryPayment", back_populates="bank_account")
    employee_advances = relationship("EmployeeAdvance", back_populates="bank_account")


class CreditCard(Base):
    __tablename__ = "credit_cards"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    bank_name = Column(String(100))
    last4 = Column(String(4))
    credit_limit = Column(Float, default=0.0, nullable=False)
    statement_day = Column(Integer, nullable=False)
    payment_offset_days = Column(Integer, default=10, nullable=False)
    currency = Column(String(3), default="TRY", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    txns = relationship("CreditCardTxn", back_populates="card", cascade="all, delete-orphan")
    statements = relationship("CreditCardStatement", back_populates="card", cascade="all, delete-orphan")


class CreditCardStatement(Base):
    __tablename__ = "credit_card_statements"

    id = Column(Integer, primary_key=True)
    card_id = Column(Integer, ForeignKey("credit_cards.id"), nullable=False)
    statement_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    total_amount = Column(Float, default=0.0, nullable=False)
    status = Column(Enum("unpaid", "paid", name="cc_statement_status"), default="unpaid", nullable=False)
    paid_at = Column(DateTime)
    # GM haftalık ödeme listesi kararı
    gm_decision = Column(String(20), nullable=True)
    gm_decision_at = Column(DateTime, nullable=True)
    gm_decision_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    gm_postpone_until = Column(Date, nullable=True)
    gm_method_override = Column(String(20), nullable=True)
    gm_decision_note = Column(Text, nullable=True)
    gm_approved_amount = Column(Float, nullable=True)
    preparer_note = Column(Text, nullable=True)

    card = relationship("CreditCard", back_populates="statements")
    txns = relationship("CreditCardTxn", back_populates="statement")


class CreditCardTxn(Base):
    __tablename__ = "credit_card_txns"

    id = Column(Integer, primary_key=True)
    card_id = Column(Integer, ForeignKey("credit_cards.id"), nullable=False)
    statement_id = Column(Integer, ForeignKey("credit_card_statements.id"), nullable=True)
    txn_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String(300))
    is_refund = Column(Boolean, default=False, nullable=False)
    ref_id = Column(Integer, ForeignKey("references.id"), nullable=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    instruction_id = Column(Integer, ForeignKey("payment_instructions.id"), nullable=True)

    card = relationship("CreditCard", back_populates="txns")
    statement = relationship("CreditCardStatement", back_populates="txns")


# ---------------------------------------------------------------------------
# Çek
# ---------------------------------------------------------------------------

class Cheque(Base):
    __tablename__ = "cheques"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("financial_vendors.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    cheque_type = Column(Enum("verilen", "alinan", name="cheque_type_enum"), nullable=False)
    cheque_no = Column(String(50))
    bank = Column(String(100))
    branch = Column(String(100))
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="TRY", nullable=False)
    cheque_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    status = Column(
        Enum("beklemede", "tahsil_edildi", "iade", "karsilıksız", "iptal", name="cheque_status_enum"),
        default="beklemede", nullable=False
    )
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Tahsilat / ödeme bilgisi
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    settled_date = Column(Date, nullable=True)
    settled_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    attachment = Column(String(300), nullable=True)  # static/cheque_docs/{filename}
    # GM haftalık ödeme listesi kararı
    gm_decision = Column(String(20), nullable=True)
    gm_decision_at = Column(DateTime, nullable=True)
    gm_decision_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    gm_postpone_until = Column(Date, nullable=True)
    gm_method_override = Column(String(20), nullable=True)
    gm_decision_note = Column(Text, nullable=True)
    gm_approved_amount = Column(Float, nullable=True)
    preparer_note = Column(Text, nullable=True)
    created_by_instruction_id = Column(Integer, ForeignKey("payment_instructions.id"), nullable=True)

    vendor = relationship("FinancialVendor", back_populates="cheques")
    customer = relationship("Customer", back_populates="cheques")
    bank_account = relationship("BankAccount", foreign_keys=[bank_account_id])
    settler = relationship("User", foreign_keys=[settled_by])


# ---------------------------------------------------------------------------
# Referans (İş / Proje)
# ---------------------------------------------------------------------------

class Reference(Base):
    __tablename__ = "references"

    id = Column(Integer, primary_key=True)
    ref_no = Column(String(30), nullable=False, unique=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    title = Column(String(300), nullable=False)
    event_type = Column(String(50))
    check_in = Column(Date)
    check_out = Column(Date)
    status = Column(
        Enum("aktif", "tamamlandi", "iptal", name="reference_status_enum"),
        default="aktif", nullable=False
    )
    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer = relationship("Customer", back_populates="references")
    creator = relationship("User")
    invoices = relationship("Invoice", back_populates="reference")
    cash_entries = relationship("CashEntry", back_populates="reference")
    bank_movements = relationship("BankMovement", back_populates="reference")
    general_expenses = relationship("GeneralExpense", back_populates="reference")


# ---------------------------------------------------------------------------
# Fatura
# ---------------------------------------------------------------------------

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    ref_id = Column(Integer, ForeignKey("references.id"), nullable=True)
    vendor_id = Column(Integer, ForeignKey("financial_vendors.id"), nullable=True)
    invoice_type = Column(
        Enum("gelen", "kesilen", "komisyon", "iade_gelen", "iade_kesilen", name="invoice_type_enum"),
        nullable=False
    )
    invoice_no = Column(String(100))
    invoice_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    vat_rate = Column(Float, default=0.20, nullable=False)
    currency = Column(String(3), default="TRY", nullable=False)
    status = Column(
        Enum("draft", "approved", "partial", "paid", "cancelled", name="invoice_status_enum"),
        default="approved", nullable=False
    )
    payment_method = Column(
        Enum("nakit", "banka", "kredi_karti", "cek", "acik_hesap", name="invoice_payment_method_enum"),
        nullable=True
    )
    paid_at = Column(DateTime)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    credit_card_id = Column(Integer, ForeignKey("credit_cards.id"), nullable=True)
    cash_book_id = Column(Integer, ForeignKey("cash_books.id"), nullable=True)
    cheque_id = Column(Integer, ForeignKey("cheques.id"), nullable=True)
    due_date = Column(Date, nullable=True)
    items_json = Column(Text, nullable=True)
    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # E-Fatura entegrasyonu (prizma-einvoice paketi tarafından kullanılır)
    einvoice_status = Column(String(20), nullable=True)
    einvoice_uuid = Column(String(64), nullable=True)
    einvoice_pdf_url = Column(Text, nullable=True)
    einvoice_sent_at = Column(DateTime, nullable=True)
    einvoice_inbox_id = Column(Integer, nullable=True)        # gelen invoice ise
    einvoice_external_uuid = Column(String(64), nullable=True)
    # GM (Genel Müdür) haftalık ödeme listesi kararı
    gm_decision = Column(String(20), nullable=True)  # approved | rejected | postponed | NULL
    gm_decision_at = Column(DateTime, nullable=True)
    gm_decision_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    gm_postpone_until = Column(Date, nullable=True)
    gm_method_override = Column(String(20), nullable=True)  # nakit|banka|kredi_karti|cek|acik_hesap
    gm_decision_note = Column(Text, nullable=True)
    gm_approved_amount = Column(Float, nullable=True)  # kısmi onay için: bu kadar onaylandı, kalan ertelendi
    preparer_note = Column(Text, nullable=True)  # listeyi hazırlayan kullanıcının GM'e yönelik notu

    reference = relationship("Reference", back_populates="invoices")
    vendor = relationship("FinancialVendor", back_populates="invoices")
    creator = relationship("User", foreign_keys=[created_by])
    bank_account = relationship("BankAccount")
    credit_card = relationship("CreditCard")
    cash_book = relationship("CashBook")
    cheque = relationship("Cheque")
    cash_entries = relationship("CashEntry", back_populates="invoice")
    bank_movements = relationship("BankMovement", back_populates="invoice")
    payments = relationship("InvoicePayment", back_populates="invoice",
                            cascade="all, delete-orphan", order_by="InvoicePayment.payment_date")

    @property
    def total_with_vat(self) -> float:
        return round(self.amount * (1 + self.vat_rate), 2)

    @property
    def paid_amount(self) -> float:
        return round(sum(p.amount for p in self.payments), 2)

    @property
    def remaining(self) -> float:
        return round(self.total_with_vat - self.paid_amount, 2)


# ---------------------------------------------------------------------------
# Kasa Hareketi & Banka Hareketi
# ---------------------------------------------------------------------------

class CashEntry(Base):
    __tablename__ = "cash_entries"

    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("cash_books.id"), nullable=False)
    entry_date = Column(Date, nullable=False)
    entry_type = Column(Enum("giris", "cikis", name="cash_entry_type_enum"), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String(300))
    category = Column(String(100), nullable=True)
    related_party = Column(String(150), nullable=True)
    ref_id = Column(Integer, ForeignKey("references.id"), nullable=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    instruction_id = Column(Integer, ForeignKey("payment_instructions.id"), nullable=True)

    book = relationship("CashBook", back_populates="entries")
    reference = relationship("Reference", back_populates="cash_entries")
    invoice = relationship("Invoice", back_populates="cash_entries")


class BankMovement(Base):
    __tablename__ = "bank_movements"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False)
    movement_date = Column(Date, nullable=False)
    movement_type = Column(Enum("giris", "cikis", name="bank_movement_type_enum"), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String(300))
    ref_id = Column(Integer, ForeignKey("references.id"), nullable=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    instruction_id = Column(Integer, ForeignKey("payment_instructions.id"), nullable=True)

    account = relationship("BankAccount", back_populates="movements")
    reference = relationship("Reference", back_populates="bank_movements")
    invoice = relationship("Invoice", back_populates="bank_movements")


class InvoicePayment(Base):
    """Faturaya bağlı kısmi veya tam ödeme taksiti."""
    __tablename__ = "invoice_payments"

    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    payment_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(
        Enum("nakit", "banka", "kredi_karti", "cek", name="inv_pmt_method_enum"),
        nullable=False
    )
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    cash_book_id = Column(Integer, ForeignKey("cash_books.id"), nullable=True)
    credit_card_id = Column(Integer, ForeignKey("credit_cards.id"), nullable=True)
    cheque_id = Column(Integer, ForeignKey("cheques.id"), nullable=True)
    notes = Column(String(300))
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    instruction_id = Column(Integer, ForeignKey("payment_instructions.id"), nullable=True)

    invoice = relationship("Invoice", back_populates="payments")
    bank_account = relationship("BankAccount")
    cash_book = relationship("CashBook")
    credit_card = relationship("CreditCard")
    cheque = relationship("Cheque")


class VendorPrepayment(Base):
    """Tedarikçiye fatura kesilmeden yapılan ön/avans ya da doğrudan ödeme."""
    __tablename__ = "vendor_prepayments"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("financial_vendors.id"), nullable=False)
    payment_type = Column(String(20), default="prepayment", nullable=False)  # prepayment | direct
    ref_id = Column(Integer, ForeignKey("references.id"), nullable=True)
    payment_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(
        Enum("nakit", "banka", "kredi_karti", "cek", name="vp_method_enum"),
        nullable=False
    )
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    cash_book_id = Column(Integer, ForeignKey("cash_books.id"), nullable=True)
    credit_card_id = Column(Integer, ForeignKey("credit_cards.id"), nullable=True)
    cheque_id = Column(Integer, ForeignKey("cheques.id"), nullable=True)
    notes = Column(String(300))
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    vendor = relationship("FinancialVendor", back_populates="prepayments")
    reference = relationship("Reference")
    bank_account = relationship("BankAccount")
    cash_book = relationship("CashBook")
    credit_card = relationship("CreditCard")
    cheque = relationship("Cheque")


# ---------------------------------------------------------------------------
# Genel Giderler
# ---------------------------------------------------------------------------

class GeneralExpenseCategory(Base):
    __tablename__ = "general_expense_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey("general_expense_categories.id"), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)

    parent = relationship("GeneralExpenseCategory", remote_side=[id], back_populates="children")
    children = relationship("GeneralExpenseCategory", back_populates="parent")
    expenses = relationship("GeneralExpense", back_populates="category")


class GeneralExpense(Base):
    __tablename__ = "general_expenses"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("general_expense_categories.id"), nullable=False)
    expense_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    vat_rate = Column(Float, default=0.0, nullable=False)
    payment_method = Column(
        Enum("nakit", "banka", "kredi_karti", name="expense_payment_method_enum"),
        nullable=True
    )
    vendor_id = Column(Integer, ForeignKey("financial_vendors.id"), nullable=True)
    ref_id = Column(Integer, ForeignKey("references.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    source = Column(
        Enum("manual", "salary", "benefit", "advance", name="expense_source_enum"),
        default="manual", nullable=False
    )
    description = Column(String(300))
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    category = relationship("GeneralExpenseCategory", back_populates="expenses")
    vendor = relationship("FinancialVendor", back_populates="general_expenses")
    reference = relationship("Reference", back_populates="general_expenses")
    employee = relationship("Employee", back_populates="general_expenses")
    creator = relationship("User")


# ---------------------------------------------------------------------------
# Çalışanlar
# ---------------------------------------------------------------------------

class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    title = Column(String(100))
    department = Column(String(100))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    gross_salary = Column(Float, default=0.0, nullable=False)
    net_salary = Column(Float, default=0.0, nullable=False)
    iban = Column(String(40))
    active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # bağlı kullanıcı hesabı

    salary_payments = relationship("SalaryPayment", back_populates="employee", cascade="all, delete-orphan")
    benefits = relationship("EmployeeBenefit", back_populates="employee", cascade="all, delete-orphan")
    advances = relationship("EmployeeAdvance", back_populates="employee", cascade="all, delete-orphan")
    general_expenses = relationship("GeneralExpense", back_populates="employee")
    user = relationship("User", foreign_keys=[user_id])


class SalaryPayment(Base):
    __tablename__ = "salary_payments"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    period = Column(String(7), nullable=False)  # YYYY-MM
    gross_amount = Column(Float, nullable=False)
    net_amount = Column(Float, nullable=False)
    payment_method = Column(Enum("nakit", "banka", name="salary_payment_method_enum"), nullable=False)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    paid_at = Column(DateTime, nullable=False)
    general_expense_id = Column(Integer, ForeignKey("general_expenses.id"), nullable=True)
    notes = Column(Text)
    instruction_id = Column(Integer, ForeignKey("payment_instructions.id"), nullable=True)

    employee = relationship("Employee", back_populates="salary_payments")
    bank_account = relationship("BankAccount", back_populates="salary_payments")
    general_expense = relationship("GeneralExpense")


class EmployeeBenefit(Base):
    __tablename__ = "employee_benefits"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    benefit_type = Column(
        Enum("yemek", "ulasim", "saglik", "diger", name="benefit_type_enum"),
        nullable=False
    )
    period = Column(String(7), nullable=False)  # YYYY-MM
    amount = Column(Float, nullable=False)
    paid_at = Column(DateTime, nullable=False)
    payment_method = Column(
        Enum("nakit", "banka", "kredi_karti", name="benefit_payment_method_enum"),
        nullable=False
    )
    general_expense_id = Column(Integer, ForeignKey("general_expenses.id"), nullable=True)
    notes = Column(Text)

    employee = relationship("Employee", back_populates="benefits")
    general_expense = relationship("GeneralExpense")


class EmployeeAdvance(Base):
    __tablename__ = "employee_advances"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    amount = Column(Float, nullable=False)
    advance_date = Column(Date, nullable=True)   # ödeme tarihi (onaylanınca set edilir)
    reason = Column(String(300))
    # "maas" = maaş avansı, "is" = iş avansı (referansa bağlı)
    advance_type = Column(String(10), default="maas", nullable=False)
    ref_id = Column(Integer, ForeignKey("references.id"), nullable=True)
    # Talep/onay akışı
    approval_status = Column(String(20), default="onaylandi", nullable=False)
    # talep | onaylandi | reddedildi
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approval_note = Column(String(300), nullable=True)
    # Ödeme
    status = Column(
        Enum("open", "partial", "closed", name="advance_status_enum"),
        default="open", nullable=False
    )
    repaid_amount = Column(Float, default=0.0, nullable=False)
    payment_method = Column(Enum("nakit", "banka", name="advance_payment_method_enum"), nullable=True)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    # İş avansı kapatma
    expense_items_json = Column(Text)
    cash_return_amount = Column(Float, default=0.0)
    closed_at = Column(Date, nullable=True)
    closed_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    employee = relationship("Employee", back_populates="advances")
    bank_account = relationship("BankAccount", back_populates="employee_advances")
    reference = relationship("Reference")
    requester = relationship("User", foreign_keys=[requested_by])
    approver = relationship("User", foreign_keys=[approved_by_id])


# ---------------------------------------------------------------------------
# Faaliyet Raporu / Yıllık Bütçe
# ---------------------------------------------------------------------------

class AnnualBudget(Base):
    __tablename__ = "annual_budgets"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False, unique=True)
    notes = Column(String(300))
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lines = relationship("BudgetLine", back_populates="budget", cascade="all, delete-orphan")


class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id = Column(Integer, primary_key=True)
    budget_id = Column(Integer, ForeignKey("annual_budgets.id"), nullable=False)
    line_type = Column(String(20), nullable=False)  # gelir | gider | maas | sabit
    category_id = Column(Integer, ForeignKey("general_expense_categories.id"), nullable=True)
    label = Column(String(150), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    month_1 = Column(Float, default=0.0, nullable=False)
    month_2 = Column(Float, default=0.0, nullable=False)
    month_3 = Column(Float, default=0.0, nullable=False)
    month_4 = Column(Float, default=0.0, nullable=False)
    month_5 = Column(Float, default=0.0, nullable=False)
    month_6 = Column(Float, default=0.0, nullable=False)
    month_7 = Column(Float, default=0.0, nullable=False)
    month_8 = Column(Float, default=0.0, nullable=False)
    month_9 = Column(Float, default=0.0, nullable=False)
    month_10 = Column(Float, default=0.0, nullable=False)
    month_11 = Column(Float, default=0.0, nullable=False)
    month_12 = Column(Float, default=0.0, nullable=False)

    budget = relationship("AnnualBudget", back_populates="lines")
    category = relationship("GeneralExpenseCategory")


class FixedExpense(Base):
    __tablename__ = "fixed_expenses"

    id = Column(Integer, primary_key=True)
    label = Column(String(150), nullable=False)
    category_id = Column(Integer, ForeignKey("general_expense_categories.id"), nullable=True)
    amount = Column(Float, nullable=False)
    recurrence = Column(String(20), default="monthly", nullable=False)  # monthly | quarterly | yearly | once
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    notes = Column(String(300))
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    category = relationship("GeneralExpenseCategory")


# ---------------------------------------------------------------------------
# HBF — Harcama Bildirim Formu
# ---------------------------------------------------------------------------

class HBF(Base):
    __tablename__ = "hbf_forms"

    id = Column(Integer, primary_key=True)
    hbf_no = Column(String(30), unique=True, nullable=False)
    ref_id = Column(Integer, ForeignKey("references.id"), nullable=True)   # birincil ref (backward compat)
    refs_json = Column(Text)            # JSON: [{"id":1,"ref_no":"TOP-ABC-2501-001"}]
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    title = Column(String(200), nullable=True)
    # items_json format: [{date, description, payment, document_type,
    #   amount_with_vat, vat_rate, vat_amount, amount_without_vat}]
    items_json = Column(Text)
    total_amount = Column(Float, default=0.0, nullable=False)   # KDV dahil genel toplam
    status = Column(
        Enum("taslak", "beklemede", "onaylandi", "reddedildi", "odendi",
             name="hbf_status_enum"),
        default="taslak", nullable=False,
    )
    notes = Column(Text)
    approval_note = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    paid_at = Column(Date, nullable=True)
    payment_method = Column(String(20), nullable=True)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    cash_book_id = Column(Integer, ForeignKey("cash_books.id"), nullable=True)
    general_expense_id = Column(Integer, ForeignKey("general_expenses.id"), nullable=True)
    # JSON: [{"filename":"uuid_xxx.pdf","original":"fiş.pdf","uploaded_at":"2026-04-24"}]
    attachments_json = Column(Text)

    reference = relationship("Reference")
    employee = relationship("Employee")
    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])
    bank_account = relationship("BankAccount")
    cash_book = relationship("CashBook")


# ---------------------------------------------------------------------------
# Fon Havuzu
# ---------------------------------------------------------------------------

class FundPool(Base):
    __tablename__ = "fund_pools"

    id             = Column(Integer, primary_key=True)
    name           = Column(String(200), nullable=False)
    customer_id    = Column(Integer, ForeignKey("customers.id"), nullable=True)
    currency       = Column(String(3), default="TRY", nullable=False)
    initial_amount = Column(Float, nullable=False)        # KDV dahil başlangıç
    vat_rate       = Column(Float, default=0.20)          # 0.20 = %20
    invoice_date   = Column(Date, nullable=True)
    invoice_no     = Column(String(100), nullable=True)
    year           = Column(Integer, nullable=True)
    notes          = Column(String(500), nullable=True)
    created_by     = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer  = relationship("Customer")
    creator   = relationship("User", foreign_keys=[created_by])
    transfers = relationship(
        "FundTransfer", back_populates="fund_pool",
        cascade="all, delete-orphan",
        order_by="FundTransfer.transfer_date",
    )


class FundTransfer(Base):
    __tablename__ = "fund_transfers"

    id            = Column(Integer, primary_key=True)
    fund_pool_id  = Column(Integer, ForeignKey("fund_pools.id"), nullable=False)
    ref_id        = Column(Integer, ForeignKey("references.id"), nullable=True)
    direction     = Column(
        Enum("out", "in", name="fund_direction_enum"), nullable=False
    )
    amount        = Column(Float, nullable=False)          # KDV dahil
    vat_rate      = Column(Float, default=0.20)
    exchange_rate = Column(Float, default=1.0)            # TRY kuru (yabancı para için)
    transfer_date = Column(Date, nullable=False)
    description   = Column(String(300), nullable=True)
    created_by    = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)

    fund_pool = relationship("FundPool", back_populates="transfers")
    reference = relationship("Reference")
    creator   = relationship("User", foreign_keys=[created_by])


HBF_STATUS_LABELS = {
    "taslak":     "Taslak",
    "beklemede":  "Beklemede",
    "onaylandi":  "Onaylandı",
    "reddedildi": "Reddedildi",
    "odendi":     "Ödendi",
}


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

EVENT_TYPES = [
    ("toplanti", "Toplantı"),
    ("konferans", "Konferans"),
    ("gala", "Gala"),
    ("egitim", "Eğitim"),
    ("lansman", "Lansman"),
    ("diger", "Diğer"),
]

EVENT_TYPE_CODES = {
    "toplanti": "TOP",
    "konferans": "KON",
    "gala": "GAL",
    "egitim": "EGT",
    "lansman": "LAN",
    "diger": "ETK",
}

INVOICE_TYPES = [
    ("gelen", "Gelen Fatura"),
    ("kesilen", "Kesilen Fatura"),
    ("komisyon", "Komisyon Faturası"),
    ("iade_gelen", "İade - Gelen"),
    ("iade_kesilen", "İade - Kesilen"),
]

PAYMENT_METHODS = [
    ("nakit", "Nakit"),
    ("banka", "Banka Havalesi"),
    ("kredi_karti", "Kredi Kartı"),
    ("cek", "Çek"),
    ("acik_hesap", "Açık Hesap"),
]

VAT_RATES = [0.0, 0.01, 0.08, 0.10, 0.18, 0.20]


# ---------------------------------------------------------------------------
# Maaş kararı (PayrollDecision) — bir ay için GM toplu maaş kararını saklar
# ---------------------------------------------------------------------------

class PayrollDecision(Base):
    __tablename__ = "payroll_decisions"

    id = Column(Integer, primary_key=True)
    period = Column(String(7), nullable=False, unique=True)  # YYYY-MM
    gm_decision = Column(String(20), nullable=True)
    gm_decision_at = Column(DateTime, nullable=True)
    gm_decision_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    gm_postpone_until = Column(Date, nullable=True)
    gm_method_override = Column(String(20), nullable=True)
    gm_decision_note = Column(Text, nullable=True)
    gm_approved_amount = Column(Float, nullable=True)
    preparer_note = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# SystemSetting — basit key-value config (örn. ödeme günü)
# ---------------------------------------------------------------------------

class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(String(500))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# ManualPaymentLine — haftalık listeye manuel olarak eklenen ödeme kalemi
# (sistemde fatura/çek/ekstre olarak kayıtlı olmayan ödemeler için)
# ---------------------------------------------------------------------------

class ManualPaymentLine(Base):
    __tablename__ = "manual_payment_lines"

    id = Column(Integer, primary_key=True)
    description = Column(String(300), nullable=False)
    party = Column(String(200))          # serbest metin tedarikçi/karşı taraf
    amount = Column(Float, nullable=False)
    payment_method = Column(String(20), default="banka", nullable=False)
    due_date = Column(Date, nullable=True)
    ref_id = Column(Integer, ForeignKey("references.id"), nullable=True)
    notes = Column(Text)
    status = Column(String(20), default="open", nullable=False)  # open | paid | cancelled
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at = Column(DateTime, nullable=True)
    # GM ödeme listesi alanları (Invoice/Cheque ile aynı)
    gm_decision = Column(String(20), nullable=True)
    gm_decision_at = Column(DateTime, nullable=True)
    gm_decision_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    gm_postpone_until = Column(Date, nullable=True)
    gm_method_override = Column(String(20), nullable=True)
    gm_decision_note = Column(Text, nullable=True)
    gm_approved_amount = Column(Float, nullable=True)
    preparer_note = Column(Text, nullable=True)

    creator = relationship("User", foreign_keys=[created_by])


# ---------------------------------------------------------------------------
# PaymentInstruction — GM onay → operatör infaz arasındaki bekleyen talimat
# ---------------------------------------------------------------------------

class PaymentInstruction(Base):
    __tablename__ = "payment_instructions"

    id = Column(Integer, primary_key=True)
    # Kaynak: hangi kalem türü için bu talimat
    source_type = Column(String(20), nullable=False)  # invoice|cheque|cc_statement|payroll
    source_id = Column(Integer, nullable=True)        # invoice.id / cheque.id / cc_statement.id
    source_period = Column(String(7), nullable=True)  # payroll için 'YYYY-MM'
    # GM onay verisi
    amount = Column(Float, nullable=False)
    payment_method = Column(String(20), nullable=False)  # nakit|banka|kredi_karti|cek
    note = Column(Text, nullable=True)
    # Operatör infaz hedefi (execution'da seçilir)
    target_bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    target_cash_book_id = Column(Integer, ForeignKey("cash_books.id"), nullable=True)
    target_credit_card_id = Column(Integer, ForeignKey("credit_cards.id"), nullable=True)
    # Durum
    status = Column(String(20), default="pending", nullable=False)  # pending|executed|cancelled
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)  # GM
    executed_at = Column(DateTime, nullable=True)
    executed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancel_reason = Column(Text, nullable=True)

    creator = relationship("User", foreign_keys=[created_by])
    executor = relationship("User", foreign_keys=[executed_by])
    canceller = relationship("User", foreign_keys=[cancelled_by])
    target_bank_account = relationship("BankAccount")
    target_cash_book = relationship("CashBook")
    target_credit_card = relationship("CreditCard")
