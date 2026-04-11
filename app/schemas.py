from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class LoginPayload(BaseModel):
    username: str
    password: str


class RequestCreate(BaseModel):
    request_date: date
    factory_id: int
    vendor_id: int
    vendor_mobile: Optional[str] = None
    item_category: str
    item_name: str
    qty: float = Field(gt=0)
    unit: str
    rate: float = Field(gt=0)
    amount: float = Field(gt=0)
    gst_percent: float = 0
    final_amount: float = Field(gt=0)
    reason: str
    urgent_flag: bool = False
    requested_by: str
    notes: Optional[str] = None
    save_as_draft: bool = False


class RequestApprove(BaseModel):
    approved_amount: float
    remarks: Optional[str] = None
    priority: Optional[str] = "Medium"
    expected_payment_date: Optional[date] = None


class RequestReject(BaseModel):
    reason: str


class PaymentCreate(BaseModel):
    payment_date: date
    payment_mode: str
    transaction_ref: Optional[str] = None
    paid_amount: float = Field(gt=0)
    partial_payment: bool = False
    remarks: Optional[str] = None
