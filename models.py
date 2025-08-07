from datetime import datetime
from http import HTTPStatus
from typing import Optional, List, Dict, Any, Generic, TypeVar, Union

from pydantic import BaseModel, Field

# Define a generic type variable for response data
T = TypeVar('T')


class TaprootAsset(BaseModel):
    """Model for a Taproot Asset."""
    id: str
    name: str
    asset_id: str
    type: str
    amount: str
    genesis_point: str
    meta_hash: str
    version: str
    is_spent: bool
    script_key: str
    channel_info: Optional[Dict[str, Any]] = None
    user_id: str
    created_at: datetime
    updated_at: datetime


class TaprootInvoiceRequest(BaseModel):
    """Request model for creating a Taproot Asset invoice."""
    asset_id: str
    amount: int
    description: Optional[str] = None
    expiry: Optional[int] = None
    peer_pubkey: Optional[str] = None  # Add peer_pubkey parameter for multi-channel support
    extra: Optional[dict] = None  # Store metadata from other extensions


class TaprootPaymentRequest(BaseModel):
    """Request model for paying a Taproot Asset invoice."""
    payment_request: str
    fee_limit_sats: Optional[int] = 10  # Default to 10 sats fee limit
    peer_pubkey: Optional[str] = None  # Add peer_pubkey for multi-channel support
    asset_id: Optional[str] = None  # Add asset_id to specify which asset to use for payment


class TaprootInvoice(BaseModel):
    """Model for a Taproot Asset invoice."""
    id: str
    payment_hash: str
    payment_request: str
    asset_id: str
    asset_amount: int
    satoshi_amount: int  # Satoshi amount for protocol requirements (from settings)
    description: Optional[str] = None
    status: str = "pending"
    user_id: str
    wallet_id: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    extra: Optional[dict] = None  # Store metadata from other extensions


class TaprootPayment(BaseModel):
    """Model for a Taproot Asset payment."""
    id: str
    payment_hash: str
    payment_request: str
    asset_id: str
    asset_amount: int
    fee_sats: int
    description: Optional[str] = None
    status: str = "completed"
    user_id: str
    wallet_id: str
    created_at: datetime
    preimage: Optional[str] = None


class AssetBalance(BaseModel):
    """Model for a user's asset balance."""
    id: str
    wallet_id: str
    asset_id: str
    balance: int
    last_payment_hash: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AssetTransaction(BaseModel):
    """Model for an asset transaction."""
    id: str
    wallet_id: str
    asset_id: str
    payment_hash: Optional[str] = None
    amount: int
    fee: int = 0
    description: Optional[str] = None
    type: str  # 'credit', 'debit'
    created_at: datetime


# API Response Models

class ErrorDetail(BaseModel):
    """Model for detailed error information."""
    code: Optional[str] = None
    source: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class ApiResponse(Generic[T]):
    """
    Generic API response model.
    
    This model provides a standardized structure for all API responses,
    with consistent fields for success status, data, and error information.
    """
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    details: Optional[ErrorDetail] = None
    
    @classmethod
    def success_response(cls, data: Optional[T] = None) -> Dict[str, Any]:
        """Create a success response."""
        return {
            "success": True,
            "data": data
        }
    
    @classmethod
    def error_response(
        cls, 
        message: str, 
        details: Optional[ErrorDetail] = None,
        status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    ) -> Dict[str, Any]:
        """Create an error response."""
        response = {
            "success": False,
            "error": message
        }
        
        if details:
            response["details"] = details
            
        return response


class InvoiceResponse(BaseModel):
    """Standardized response for invoice creation."""
    payment_hash: str
    payment_request: str
    asset_id: str
    asset_amount: int
    satoshi_amount: int
    checking_id: str


class PaymentResponse(BaseModel):
    """Standardized response for payment operations."""
    success: bool
    payment_hash: str
    preimage: Optional[str] = None
    fee_msat: Optional[int] = None
    sat_fee_paid: Optional[int] = None
    routing_fees_sats: Optional[int] = None
    asset_amount: int
    asset_id: Optional[str] = None
    description: Optional[str] = None
    internal_payment: Optional[bool] = False
    status: str = "success"  # Can be "success" or "failed"
    error: Optional[str] = None  # Error message if payment failed
    lnurl_success_action: Optional[Dict[str, Any]] = None  # LNURL success action if present


class ParsedInvoice(BaseModel):
    """Model for parsed invoice data."""
    payment_hash: str
    amount: float
    description: Optional[str] = ""
    expiry: int
    timestamp: int
    valid: bool
    asset_id: Optional[str] = None
    destination: Optional[str] = None  # Destination node pubkey


class LnurlPayRequest(BaseModel):
    """Request model for LNURL pay."""
    lnurl: str
    amount_msat: int
    comment: Optional[str] = None
    asset_id: Optional[str] = None
    fee_limit_sats: Optional[int] = 100


class LnurlInfoRequest(BaseModel):
    """Request model for LNURL info/parsing."""
    lnurl: str
