"""Request models for financial entries. Amounts are Decimals with at most 2 decimal
places — they are never floats. The browser sends simple forms; the server decides
the accounting (debit/credit lines) in app/ledger.py."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

Money = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
Text100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Text500 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Method = Literal["cash", "bank_transfer", "upi", "cheque", "other"]
Action = Literal["draft", "submit", "post"]

MIN_DATE = date(2000, 1, 1)


class _Base(BaseModel):
    model_config = {"extra": "forbid"}


class _EntryCommon(_Base):
    entry_date: date
    description: Text500
    notes: Notes | None = None
    site_id: uuid.UUID | None = None
    action: Action = "draft"

    @model_validator(mode="after")
    def _date_ok(self):
        if self.entry_date < MIN_DATE:
            raise ValueError("date is too far in the past")
        if (self.entry_date - date.today()).days > 31:
            raise ValueError("date is more than a month in the future")
        return self


class Allocation(_Base):
    bill_id: uuid.UUID
    amount: Money


def _check_allocations(allocs: list[Allocation], total: Decimal) -> None:
    if len({a.bill_id for a in allocs}) != len(allocs):
        raise ValueError("the same bill appears twice")
    if sum((a.amount for a in allocs), Decimal(0)) > total:
        raise ValueError("amounts allocated to bills exceed the amount received/paid")


class ReceiptIn(_EntryCommon):
    """Money received. customer_payment reduces what the customer owes (never income);
    advance is a liability until billed; other_income is genuine income."""
    receipt_kind: Literal["customer_payment", "advance", "other_income"]
    party_id: uuid.UUID | None = None
    amount: Money
    money_account_id: uuid.UUID
    payment_method: Method
    reference_no: Text100 | None = None
    income_account_id: uuid.UUID | None = None
    allocations: list[Allocation] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _rules(self):
        if self.receipt_kind in ("customer_payment", "advance") and not self.party_id:
            raise ValueError("choose the customer")
        if self.receipt_kind == "other_income" and not self.income_account_id:
            raise ValueError("choose the income account")
        if self.allocations and self.receipt_kind != "customer_payment":
            raise ValueError("only customer payments can be applied to bills")
        _check_allocations(self.allocations, self.amount)
        return self


class ExpenseIn(_EntryCommon):
    expense_account_id: uuid.UUID
    amount: Money
    money_account_id: uuid.UUID
    payment_method: Method
    party_id: uuid.UUID | None = None
    reference_no: Text100 | None = None


class SupplierPaymentIn(_EntryCommon):
    """Money paid to a supplier against what we owe them (reduces payables, not an expense)."""
    party_id: uuid.UUID
    amount: Money
    money_account_id: uuid.UUID
    payment_method: Method
    reference_no: Text100 | None = None
    allocations: list[Allocation] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _rules(self):
        _check_allocations(self.allocations, self.amount)
        return self


class TransferIn(_EntryCommon):
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Money
    payment_method: Method = "bank_transfer"
    reference_no: Text100 | None = None

    @model_validator(mode="after")
    def _rules(self):
        if self.from_account_id == self.to_account_id:
            raise ValueError("choose two different accounts")
        return self


class InstallmentIn(_Base):
    due_date: date
    expected_amount: Money


class BillIn(_EntryCommon):
    direction: Literal["receivable", "payable"]
    bill_no: Text100
    party_id: uuid.UUID
    due_date: date | None = None
    period_from: date | None = None
    period_to: date | None = None
    amount: Money
    account_id: uuid.UUID  # income account (receivable) or expense account (payable)
    installments: list[InstallmentIn] = Field(default_factory=list, max_length=120)

    @model_validator(mode="after")
    def _rules(self):
        if self.due_date and self.due_date < self.entry_date:
            raise ValueError("due date cannot be before the bill date")
        if self.period_from and self.period_to and self.period_to < self.period_from:
            raise ValueError("period end is before period start")
        if sum((i.expected_amount for i in self.installments), Decimal(0)) > self.amount:
            raise ValueError("installments add up to more than the bill amount")
        if len({i.due_date for i in self.installments}) != len(self.installments):
            raise ValueError("two installments have the same due date")
        return self


class OpeningLine(_Base):
    account_id: uuid.UUID
    party_id: uuid.UUID | None = None
    side: Literal["debit", "credit"]
    amount: Money


class OpeningIn(_EntryCommon):
    balances: list[OpeningLine] = Field(min_length=1, max_length=200)


class VersionIn(_Base):
    version: int


class ReasonIn(_Base):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class DecisionIn(_Base):
    decision: Literal["approve", "reject"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


ENTRY_MODELS = {
    "receipt": ReceiptIn,
    "expense": ExpenseIn,
    "payment": SupplierPaymentIn,
    "transfer": TransferIn,
    "bill": BillIn,
    "opening": OpeningIn,
}


class SheetExpense(_Base):
    account_id: uuid.UUID
    amount: Money
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None


class MonthlySheetIn(_EntryCommon):
    """One row of the owner's Excel sheet, entered in a single form. The server turns it into
    a customer bill, a receipt (applied to that bill) and one expense per payment line."""
    description: Text500 | None = None  # type: ignore[assignment]  # generated when empty
    party_id: uuid.UUID | None = None
    bill_no: Text100 | None = None
    monthly_bill: Money | None = None
    income_account_id: uuid.UUID | None = None
    period_from: date | None = None
    period_to: date | None = None
    due_date: date | None = None
    installment_received: Money | None = None
    received_into_id: uuid.UUID | None = None
    receipt_method: Method = "cash"
    receipt_no: Text100 | None = None
    expenses: list[SheetExpense] = Field(default_factory=list, max_length=20)
    paid_from_id: uuid.UUID | None = None
    expense_method: Method = "cash"

    @model_validator(mode="after")
    def _rules(self):
        if not (self.monthly_bill or self.installment_received or self.expenses):
            raise ValueError("enter at least one amount (monthly bill, installment received or an expense)")
        if (self.monthly_bill or self.installment_received) and not self.party_id:
            raise ValueError("choose the customer")
        if self.monthly_bill and not self.bill_no:
            raise ValueError("enter the bill number")
        if self.installment_received and not self.received_into_id:
            raise ValueError("choose where the installment was received (cash or bank)")
        if self.expenses and not self.paid_from_id:
            raise ValueError("choose where the expenses were paid from (cash or bank)")
        if self.period_from and self.period_to and self.period_to < self.period_from:
            raise ValueError("period end is before period start")
        return self
