from http import HTTPStatus
from typing import Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from lnbits.core.models import User, WalletTypeInfo
from lnbits.decorators import check_user_exists, require_admin_key
from pydantic import BaseModel

from .error_utils import raise_http_exception, handle_api_error
from .logging_utils import log_debug, log_info, log_warning, log_error, API
from .models import TaprootInvoiceRequest, TaprootPaymentRequest, LnurlPayRequest, LnurlInfoRequest

# Import services
from .services.asset_service import AssetService
from .services.invoice_service import InvoiceService
from .services.payment_service import PaymentService
from .services.lnurl_service import LnurlService

# The parent router in __init__.py already adds the "/taproot_assets" prefix
# So we only need to add the API path here
taproot_assets_api_router = APIRouter(prefix="/api/v1/taproot", tags=["taproot_assets"])


@taproot_assets_api_router.get("/parse-invoice", status_code=HTTPStatus.OK)
@handle_api_error
async def api_parse_invoice(
    payment_request: str = Query(..., description="BOLT11 payment request or LNURL to parse"),
    wallet: WalletTypeInfo = Depends(require_admin_key),
    force_asset: Optional[str] = Query(None, description="Force use of specific asset ID for LNURL"),
):
    """
    Parse a BOLT11 payment request or LNURL to extract invoice details for Taproot Assets.
    
    If an LNURL is provided, it will fetch the invoice and parse it as a taproot asset invoice.
    """
    log_debug(API, f"Parsing payment request for wallet {wallet.wallet.id}")
    
    # Check if this is an LNURL (starts with "lnurl" case-insensitive)
    if payment_request.lower().startswith("lnurl"):
        log_info(API, "Detected LNURL, processing as taproot asset payment")
        
        try:
            # Get LNURL info first
            lnurl_info = await LnurlService.check_lnurl_asset_support(payment_request)
            
            # Check if there's an error
            if lnurl_info.get("error"):
                raise Exception(f"LNURL Error: {lnurl_info['error']}")
            
            # Get min/max amounts
            min_sendable = lnurl_info.get("min_sendable", 0)
            max_sendable = lnurl_info.get("max_sendable", 0)
            
            # Use the minimum amount for the invoice request (user can adjust later)
            amount_msat = min_sendable if min_sendable > 0 else 1000000  # Default 1000 sats
            
            # Check if we should process as taproot asset
            # Either: 1) LNURL explicitly supports assets, 2) force_asset is provided, or 3) we're in taproot extension
            process_as_asset = False
            selected_asset = None
            
            if force_asset:
                # Force a specific asset
                log_info(API, f"Forcing use of asset {force_asset}")
                assets = await AssetService.list_assets(wallet)
                for asset in assets:
                    if asset["asset_id"] == force_asset:
                        selected_asset = asset
                        process_as_asset = True
                        break
                if not selected_asset:
                    raise Exception(f"Asset {force_asset} not found in your wallet")
            elif lnurl_info.get("supports_assets") and lnurl_info.get("accepted_asset_ids"):
                # LNURL explicitly supports assets
                assets = await AssetService.list_assets(wallet)
                accepted_ids = lnurl_info.get("accepted_asset_ids", [])
                
                # Find the first asset the user has that's accepted
                for asset in assets:
                    if asset["asset_id"] in accepted_ids:
                        selected_asset = asset
                        process_as_asset = True
                        break
                
                if not selected_asset:
                    # User doesn't have any accepted assets
                    raise Exception("You don't have any of the assets accepted by this LNURL")
            else:
                # LNURL doesn't explicitly support assets, but we're in taproot extension
                # Try to use the first available asset
                log_info(API, "LNURL doesn't explicitly support assets, checking if we can use it anyway")
                assets = await AssetService.list_assets(wallet)
                if assets and len(assets) > 0:
                    selected_asset = assets[0]  # Use the first available asset
                    process_as_asset = True
                    log_info(API, f"Using first available asset: {selected_asset['asset_id']}")
                else:
                    raise Exception("No taproot assets available in your wallet")
                
            if process_as_asset and selected_asset:
                # Fetch the invoice with the asset_id
                log_info(API, f"Fetching taproot asset invoice for asset {selected_asset['asset_id']}")
                
                # Get the invoice from LNURL callback
                import httpx
                try:
                    from lnurl import url_decode as lnurl_decode
                except ImportError:
                    # Fallback for newer versions of lnurl package
                    from lnurl import decode as lnurl_decode
                from lnbits.helpers import check_callback_url
                
                # Decode LNURL to get URL
                url = str(lnurl_decode(payment_request))
                check_callback_url(url)
                
                # First get LNURL params
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=10)
                    data = resp.json()
                    
                    if data.get("status") == "ERROR":
                        raise Exception(f"LNURL Error: {data.get('reason', 'Unknown error')}")
                    
                    # Make callback with asset_id
                    callback_url = data["callback"]
                    callback_params = {
                        "amount": amount_msat,
                        "asset_id": selected_asset["asset_id"]
                    }
                    
                    # Get the invoice
                    cb_resp = await client.get(callback_url, params=callback_params, timeout=10)
                    cb_data = cb_resp.json()
                    
                    if cb_data.get("status") == "ERROR":
                        raise Exception(f"Callback Error: {cb_data.get('reason', 'Unknown error')}")
                    
                    if not cb_data.get("pr"):
                        raise Exception("No payment request received from LNURL")
                    
                    # Now parse the taproot asset invoice
                    parsed = await PaymentService.parse_invoice(cb_data["pr"])
                    response = parsed.dict()
                    response["is_lnurl"] = True
                    response["lnurl_string"] = payment_request
                    response["asset_info"] = {
                        "asset_id": selected_asset["asset_id"],
                        "asset_name": selected_asset["name"],
                        "user_balance": selected_asset.get("user_balance", 0)
                    }
                    response["lnurl_params"] = {
                        "min_amount": min_sendable // 1000,  # Convert to sats
                        "max_amount": max_sendable // 1000,
                        "supports_assets": lnurl_info.get("supports_assets", False),
                        "accepted_asset_ids": lnurl_info.get("accepted_asset_ids", [])
                    }
                    return response
                
        except Exception as e:
            log_error(API, f"Failed to process LNURL: {str(e)}")
            raise
    
    # Otherwise, parse as normal BOLT11 invoice
    parsed_invoice = await PaymentService.parse_invoice(payment_request)
    response = parsed_invoice.dict()
    response["is_lnurl"] = False
    return response


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


@taproot_assets_api_router.post("/lnurl/info", status_code=HTTPStatus.OK)
@handle_api_error
async def api_lnurl_info(
    data: LnurlInfoRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """
    Get information about an LNURL pay link, including asset support.
    """
    log_info(API, f"Getting LNURL info for wallet {wallet.wallet.id}")
    return await LnurlService.check_lnurl_asset_support(data.lnurl)


@taproot_assets_api_router.get("/rate/{asset_id}", status_code=HTTPStatus.OK)
@handle_api_error
async def api_get_asset_rate(
    asset_id: str,
    amount: int = Query(1, description="Amount to get rate for"),
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """
    Get current RFQ rate for an asset.
    Returns the rate in sats per asset unit.
    """
    log_info(API, f"Getting rate for asset {asset_id}, amount={amount}")
    
    try:
        # Import required modules
        from .tapd.taproot_factory import TaprootAssetsFactory
        from ...wallets.tapd_grpc_files.rfqrpc import rfq_pb2, rfq_pb2_grpc
        
        # Create wallet instance
        taproot_wallet = await TaprootAssetsFactory.create_wallet(
            user_id=wallet.wallet.user,
            wallet_id=wallet.wallet.id
        )
        
        # Get RFQ stub
        rfq_stub = rfq_pb2_grpc.RfqStub(taproot_wallet.node.channel)
        
        # Find peer with asset channel
        assets = await AssetService.list_assets(wallet)
        peer_pubkey = None
        
        for asset in assets:
            if asset.get("asset_id") == asset_id and asset.get("channel_info") and asset["channel_info"].get("peer_pubkey"):
                peer_pubkey = asset["channel_info"]["peer_pubkey"]
                break
        
        if not peer_pubkey:
            return {
                "error": "No peer found with channel for this asset",
                "rate_per_unit": None
            }
        
        # Create buy order request
        buy_order_request = rfq_pb2.AddAssetBuyOrderRequest(
            asset_specifier=rfq_pb2.AssetSpecifier(asset_id=bytes.fromhex(asset_id)),
            asset_max_amt=amount,
            expiry=int((datetime.now(timezone.utc) + timedelta(minutes=1)).timestamp()),
            timeout_seconds=5,
            peer_pub_key=bytes.fromhex(peer_pubkey)
        )
        
        # Get quote
        buy_order_response = await rfq_stub.AddAssetBuyOrder(buy_order_request, timeout=5)
        
        if buy_order_response.accepted_quote:
            # Extract rate
            rate_info = buy_order_response.accepted_quote.ask_asset_rate
            total_millisats = float(rate_info.coefficient) / (10 ** rate_info.scale)
            rate_per_unit = (total_millisats / amount) / 1000
            
            return {
                "asset_id": asset_id,
                "amount": amount,
                "rate_per_unit": rate_per_unit,
                "total_sats": int(amount * rate_per_unit),
                "quote_id": buy_order_response.accepted_quote.id.hex()
            }
        else:
            return {
                "error": "No RFQ quote received",
                "rate_per_unit": None
            }
            
    except Exception as e:
        log_error(API, f"Failed to get rate: {str(e)}")
        return {
            "error": str(e),
            "rate_per_unit": None
        }


@taproot_assets_api_router.post("/lnurl/pay", status_code=HTTPStatus.OK)
@handle_api_error
async def api_lnurl_pay(
    data: LnurlPayRequest,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """
    Pay an LNURL pay link using Taproot Assets.
    
    This endpoint:
    1. Decodes the LNURL
    2. Fetches payment parameters
    3. Requests an invoice with the specified amount (and asset_id if supported)
    4. Pays the invoice using the Taproot Assets payment service
    """
    log_info(API, f"Processing LNURL payment for wallet {wallet.wallet.id}, amount={data.amount_msat} msat")
    
    # Process the LNURL payment
    payment_response = await LnurlService.pay_lnurl(
        lnurl_string=data.lnurl,
        amount_msat=data.amount_msat,
        wallet_info=wallet,
        comment=data.comment,
        asset_id=data.asset_id
    )
    
    return payment_response.dict()
