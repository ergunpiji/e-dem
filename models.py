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
    email = Column(String(200), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

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
    notes = Column(Text)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    invoices = relationship("Invoice", back_populates="vendor")
    cheques = relationship("Cheque", back_populates="vendor")
    general_expenses = relationship("GeneralExpense", back_populates="vendor")


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
        Enum("beklemede", "tahsil_edildi", "iade", "karsilıksız", name="cheque_status_enum"),
        default="beklemede", nullable=False
    )
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    vendor = relationship("FinancialVendor", back_populates="cheques")
    customer = relationship("Customer", back_populates="cheques")


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
        Enum("draft", "approved", "paid", "cancelled", name="invoice_status_enum"),
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

    reference = relationship("Reference", back_populates="invoices")
    vendor = relationship("FinancialVendor", back_populates="invoices")
    creator = relationship("User")
    bank_account = relationship("BankAccount")
    credit_card = relationship("CreditCard")
    cash_book = relationship("CashBook")
    cheque = relationship("Cheque")
    cash_entries = relationship("CashEntry", back_populates="invoice")
    bank_movements = relationship("BankMovement", back_populates="invoice")


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
    ref_id = Column(Integer, ForeignKey("references.id"), nullable=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)

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

    account = relationship("BankAccount", back_populates="movements")
    reference = relationship("Reference", back_populates="bank_movements")
    invoice = relationship("Invoice", back_populates="bank_movements")


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

    salary_payments = relationship("SalaryPayment", back_populates="employee", cascade="all, delete-orphan")
    benefits = relationship("EmployeeBenefit", back_populates="employee", cascade="all, delete-orphan")
    advances = relationship("EmployeeAdvance", back_populates="employee", cascade="all, delete-orphan")
    general_expenses = relationship("GeneralExpense", back_populates="employee")


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
    advance_date = Column(Date, nullable=False)
    reason = Column(String(300))
    status = Column(
        Enum("open", "partial", "closed", name="advance_status_enum"),
        default="open", nullable=False
    )
    repaid_amount = Column(Float, default=0.0, nullable=False)
    payment_method = Column(Enum("nakit", "banka", name="advance_payment_method_enum"), nullable=False)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)

    employee = relationship("Employee", back_populates="advances")
    bank_account = relationship("BankAccount", back_populates="employee_advances")


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
