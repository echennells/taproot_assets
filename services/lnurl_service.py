"""
LNURL service for Taproot Assets extension.
Handles LNURL pay functionality for taproot assets.
"""
from typing import Dict, Any, Optional
import httpx
from loguru import logger

try:
    from lnurl import url_decode as lnurl_decode
except ImportError:
    # Fallback for newer versions of lnurl package
    from lnurl import decode as lnurl_decode
from lnbits.helpers import check_callback_url
from lnbits.bolt11 import decode as bolt11_decode

from ..models import TaprootPaymentRequest, PaymentResponse
from ..logging_utils import log_debug, log_info, log_warning, log_error, PAYMENT, API
from ..error_utils import ErrorContext
from .payment_service import PaymentService


class LnurlService:
    """
    Service for handling LNURL payments with Taproot Assets.
    """
    
    @classmethod
    async def parse_lnurl(cls, lnurl_string: str) -> Dict[str, Any]:
        """
        Parse an LNURL string and fetch the payment parameters.
        
        Args:
            lnurl_string: The LNURL string to parse
            
        Returns:
            Dict containing the LNURL parameters
            
        Raises:
            Exception: If LNURL parsing or fetching fails
        """
        with ErrorContext("parse_lnurl", API):
            try:
                # Decode the LNURL to get the actual URL
                url = str(lnurl_decode(lnurl_string))
                log_info(API, f"Decoded LNURL to URL: {url}")
                
                # Validate the callback URL
                check_callback_url(url)
                
                # Fetch the LNURL parameters
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, timeout=10)
                    response.raise_for_status()
                    
                    data = response.json()
                    log_debug(API, f"LNURL response: {data}")
                    
                    # Check for errors
                    if data.get("status") == "ERROR":
                        raise Exception(f"LNURL error: {data.get('reason', 'Unknown error')}")
                    
                    # Validate required fields
                    if not all(key in data for key in ["callback", "minSendable", "maxSendable", "metadata"]):
                        raise Exception("Invalid LNURL response: missing required fields")
                    
                    # Add the decoded URL for reference
                    data["decoded_url"] = url
                    
                    return data
                    
            except Exception as e:
                log_error(API, f"Failed to parse LNURL: {str(e)}")
                raise
    
    @classmethod
    async def pay_lnurl(
        cls,
        lnurl_string: str,
        amount_msat: int,
        wallet_info: Any,
        comment: Optional[str] = None,
        asset_id: Optional[str] = None
    ) -> PaymentResponse:
        """
        Pay an LNURL with a specified amount, optionally using a Taproot Asset.
        
        Args:
            lnurl_string: The LNURL string to pay
            amount_msat: Amount to pay in millisatoshis
            wallet_info: Wallet information for the payment
            comment: Optional comment to include with payment
            asset_id: Optional Taproot Asset ID to use for payment
            
        Returns:
            PaymentResponse: The payment result
            
        Raises:
            Exception: If payment fails
        """
        with ErrorContext("pay_lnurl", PAYMENT):
            try:
                # Parse the LNURL first
                lnurl_params = await cls.parse_lnurl(lnurl_string)
                
                # Skip amount validation entirely for taproot assets
                # The min/max limits from LNURL are in sats, but we're paying with assets
                # which have their own units and values (1 asset could be worth 1000 sats or 0.001 sats)
                
                # Check if comment is allowed
                comment_allowed = lnurl_params.get("commentAllowed", 0)
                if comment and len(comment) > comment_allowed:
                    comment = comment[:comment_allowed]
                
                # Make the callback to get the invoice
                callback_url = lnurl_params["callback"]
                log_info(PAYMENT, f"Making LNURL callback to: {callback_url}")
                
                # Prepare callback parameters
                callback_params = {"amount": amount_msat}
                if comment and comment_allowed > 0:
                    callback_params["comment"] = comment
                
                # If this LNURL accepts assets and we have an asset_id, include it
                if asset_id and lnurl_params.get("acceptsAssets"):
                    accepted_assets = lnurl_params.get("acceptedAssetIds", [])
                    if asset_id in accepted_assets:
                        callback_params["asset_id"] = asset_id
                        log_info(PAYMENT, f"Including asset_id {asset_id} in LNURL callback")
                    else:
                        log_warning(PAYMENT, f"Asset {asset_id} not in accepted list: {accepted_assets}")
                
                # Make the callback request
                async with httpx.AsyncClient() as client:
                    check_callback_url(callback_url)
                    log_info(PAYMENT, f"Making LNURL callback with params: {callback_params}")
                    response = await client.get(
                        callback_url,
                        params=callback_params,
                        timeout=10
                    )
                    response.raise_for_status()
                    
                    callback_data = response.json()
                    log_info(PAYMENT, f"LNURL callback response: {callback_data}")
                    
                    # Check for errors
                    if callback_data.get("status") == "ERROR":
                        raise Exception(f"LNURL callback error: {callback_data.get('reason', 'Unknown error')}")
                    
                    # Get the payment request
                    payment_request = callback_data.get("pr")
                    if not payment_request:
                        raise Exception("No payment request received from LNURL callback")
                    
                    log_info(PAYMENT, f"Got payment request: {payment_request[:100]}...")
                    
                    # For taproot assets, skip bolt11 validation since the invoice format might be different
                    if asset_id:
                        log_info(PAYMENT, "Skipping bolt11 validation for taproot asset payment")
                    else:
                        # Validate the invoice amount matches what we requested
                        decoded_invoice = bolt11_decode(payment_request)
                        invoice_amount_msat = decoded_invoice.amount_msat
                        
                        # Allow small differences due to rounding
                        if abs(invoice_amount_msat - amount_msat) > 1000:  # 1 sat tolerance
                            raise ValueError(
                                f"Invoice amount {invoice_amount_msat} msat doesn't match "
                                f"requested amount {amount_msat} msat"
                            )
                    
                    # Create payment request
                    payment_data = TaprootPaymentRequest(
                        payment_request=payment_request,
                        asset_id=asset_id,
                        fee_limit_sats=100  # Default fee limit for LNURL payments
                    )
                    
                    # Process the payment using the regular payment service
                    log_info(PAYMENT, f"Processing LNURL payment with asset_id={asset_id}, payment_request={payment_request[:50]}...")
                    payment_response = await PaymentService.process_payment(
                        data=payment_data,
                        wallet=wallet_info
                    )
                    
                    log_info(PAYMENT, f"Payment response: success={payment_response.success}, status={payment_response.status}, error={payment_response.error}")
                    
                    # Add LNURL success action to the response if available
                    if payment_response.success and callback_data.get("successAction"):
                        payment_response.lnurl_success_action = callback_data["successAction"]
                        log_info(PAYMENT, f"Added success action: {callback_data.get('successAction')}")
                    
                    return payment_response
                    
            except Exception as e:
                log_error(PAYMENT, f"Failed to pay LNURL: {str(e)}")
                # Return a failed payment response
                return PaymentResponse(
                    success=False,
                    payment_hash="",
                    status="failed",
                    error=str(e),
                    asset_amount=0,
                    asset_id=asset_id or ""
                )
    
    @classmethod
    async def check_lnurl_asset_support(
        cls,
        lnurl_string: str
    ) -> Dict[str, Any]:
        """
        Check if an LNURL supports Taproot Assets and which assets it accepts.
        
        Args:
            lnurl_string: The LNURL string to check
            
        Returns:
            Dict containing asset support information
        """
        try:
            lnurl_params = await cls.parse_lnurl(lnurl_string)
            
            # Log the full response for debugging
            log_debug(API, f"LNURL params received: {lnurl_params}")
            
            result = {
                "supports_assets": lnurl_params.get("acceptsAssets", False),
                "accepted_asset_ids": lnurl_params.get("acceptedAssetIds", []),
                "asset_metadata": lnurl_params.get("assetMetadata", {}),
                "min_sendable": lnurl_params.get("minSendable", 0),
                "max_sendable": lnurl_params.get("maxSendable", 0),
                "comment_allowed": lnurl_params.get("commentAllowed", 0),
                "description": lnurl_params.get("metadata", ""),
                "callback": lnurl_params.get("callback", "")
            }
            
            log_info(API, f"LNURL asset support: supports_assets={result['supports_assets']}, accepted_ids={result['accepted_asset_ids']}")
            
            return result
        except Exception as e:
            log_error(API, f"Failed to check LNURL asset support: {str(e)}")
            return {
                "supports_assets": False,
                "error": str(e)
            }