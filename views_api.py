from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Depends, Query
from lnbits.core.models import User, WalletTypeInfo
from lnbits.decorators import check_user_exists, require_admin_key
from pydantic import BaseModel

from .error_utils import raise_http_exception, handle_api_error
from .logging_utils import log_debug, log_info, log_warning, log_error, API
from .models import TaprootInvoiceRequest, TaprootPaymentRequest

# Import services
from .services.asset_service import AssetService
from .services.invoice_service import InvoiceService
from .services.payment_service import PaymentService

# The parent router in __init__.py already adds the "/taproot_assets" prefix
# So we only need to add the API path here
taproot_assets_api_router = APIRouter(prefix="/api/v1/taproot", tags=["taproot_assets"])


@taproot_assets_api_router.get("/parse-invoice", status_code=HTTPStatus.OK)
@handle_api_error
async def api_parse_invoice(
    payment_request: str = Query(..., description="BOLT11 payment request to parse"),
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """
    Parse a BOLT11 payment request to extract invoice details for Taproot Assets.
    """
    log_debug(API, f"Parsing invoice for wallet {wallet.wallet.id}")
    parsed_invoice = await PaymentService.parse_invoice(payment_request)
    return parsed_invoice.dict()


@taproot_assets_api_router.get("/listassets", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_assets(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Assets for the current user with balance information."""
    log_debug(API, f"Listing assets for wallet {wallet.wallet.id}")
    return await AssetService.list_assets(wallet)


@taproot_assets_api_router.post("/invoice", status_code=HTTPStatus.CREATED)
@handle_api_error
async def api_create_invoice(
    data: TaprootInvoiceRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Create an invoice for a Taproot Asset."""
    log_info(API, f"Creating invoice for asset {data.asset_id}, amount={data.amount}, wallet={wallet.wallet.id}")
    return await InvoiceService.create_invoice(data, wallet.wallet.user, wallet.wallet.id)


@taproot_assets_api_router.post("/pay", status_code=HTTPStatus.OK)
@handle_api_error
async def api_pay_invoice(
    data: TaprootPaymentRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Pay a Taproot Asset invoice."""
    log_info(API, f"Processing payment request for wallet {wallet.wallet.id}")
    return await PaymentService.process_payment(data, wallet)



@taproot_assets_api_router.get("/payments", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_payments(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Asset payments for the current user."""
    log_debug(API, f"Listing payments for user {wallet.wallet.user}")
    return await PaymentService.get_user_payments(wallet.wallet.user)


@taproot_assets_api_router.get("/invoices", status_code=HTTPStatus.OK)
@handle_api_error
async def api_list_invoices(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """List all Taproot Asset invoices for the current user."""
    log_debug(API, f"Listing invoices for user {wallet.wallet.user}")
    return await InvoiceService.get_user_invoices(wallet.wallet.user)


@taproot_assets_api_router.get("/invoices/{invoice_id}", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_invoice(
    invoice_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get a specific Taproot Asset invoice by ID."""
    log_debug(API, f"Getting invoice {invoice_id} for user {wallet.wallet.user}")
    return await InvoiceService.get_invoice(invoice_id, wallet.wallet.user)


@taproot_assets_api_router.put("/invoices/{invoice_id}/status", status_code=HTTPStatus.OK)
@handle_api_error
async def api_update_invoice_status(
    invoice_id: str,
    status: str = Query(..., description="New status for the invoice"),
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Update the status of a Taproot Asset invoice."""
    log_info(API, f"Updating invoice {invoice_id} status to {status} for user {wallet.wallet.user}")
    return await InvoiceService.update_invoice_status(invoice_id, status, wallet.wallet.user, wallet.wallet.id)


@taproot_assets_api_router.get("/asset-balances", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset_balances(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get all asset balances for the current wallet."""
    log_debug(API, f"Getting asset balances for wallet {wallet.wallet.id}")
    return await AssetService.get_asset_balances(wallet)


@taproot_assets_api_router.get("/asset-balance/{asset_id}", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset_balance(
    asset_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Get the balance for a specific asset in the current wallet."""
    log_debug(API, f"Getting balance for asset {asset_id} in wallet {wallet.wallet.id}")
    return await AssetService.get_asset_balance(asset_id, wallet)


@taproot_assets_api_router.get("/asset-transactions", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset_transactions(
    wallet: WalletTypeInfo = Depends(require_admin_key),
    asset_id: Optional[str] = None,
    limit: int = 100,
):
    """Get asset transactions for the current wallet."""
    log_debug(API, f"Getting asset transactions for wallet {wallet.wallet.id}, asset_id={asset_id or 'all'}, limit={limit}")
    return await AssetService.get_asset_transactions(wallet, asset_id, limit)
