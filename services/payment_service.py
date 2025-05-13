"""
Payment service for Taproot Assets extension.
Handles payment-related business logic.
"""
from typing import Dict, Any, Optional, List, Tuple, Union
import re
import grpc
import asyncio
from http import HTTPStatus
from fastapi import HTTPException
from loguru import logger
import bolt11

from lnbits.core.models import WalletTypeInfo

from ..models import TaprootPaymentRequest, PaymentResponse, ParsedInvoice, TaprootPayment
from ..logging_utils import log_debug, log_info, log_warning, log_error, PAYMENT, API
from ..tapd.taproot_factory import TaprootAssetsFactory
from ..error_utils import raise_http_exception, ErrorContext, handle_error
# Import from crud re-exports
from ..crud import (
    get_invoice_by_payment_hash,
    is_internal_payment,
    is_self_payment,
    get_user_payments
)
from .settlement_service import SettlementService


class PaymentService:
    """
    Service for handling Taproot Asset payments.
    This service encapsulates all payment-related business logic.
    """
    
    @classmethod
    async def process_payment(
        cls,
        data: TaprootPaymentRequest,
        wallet: WalletTypeInfo,
        force_payment_type: Optional[str] = None
    ) -> PaymentResponse:
        """
        Process a payment request, automatically determining the payment type
        unless a specific type is forced.
        
        Args:
            data: The payment request data
            wallet: The wallet information
            force_payment_type: Optional parameter to force a specific payment type
                           ("internal" or "external")
        
        Returns:
            PaymentResponse: The payment result
        """
        try:
            with ErrorContext("process_payment", PAYMENT):
                # Parse the invoice to get payment details
                parsed_invoice = await cls.parse_invoice(data.payment_request)
                
                # Determine the payment type if not forced
                if force_payment_type:
                    payment_type = force_payment_type
                    log_info(PAYMENT, f"Using forced payment type: {payment_type}")
                else:
                    payment_type = await cls.determine_payment_type(
                        parsed_invoice.payment_hash, wallet.wallet.user
                    )
                    log_info(PAYMENT, f"Payment type determined: {payment_type}")
                
                # Reject self-payments
                if payment_type == "self":
                    log_warning(PAYMENT, f"Self-payment rejected for payment hash: {parsed_invoice.payment_hash}")
                    return PaymentResponse(
                        success=False,
                        payment_hash=parsed_invoice.payment_hash,
                        status="failed",
                        error="Self-payments are not allowed. You cannot pay your own invoice.",
                        asset_amount=parsed_invoice.amount,
                        asset_id=parsed_invoice.asset_id
                    )
                
                # Process based on payment type
                if payment_type == "internal":
                    return await cls._process_internal_payment(data, wallet, parsed_invoice)
                else:
                    return await cls._process_external_payment(data, wallet, parsed_invoice)
        except Exception as e:
            # Handle any exceptions and return a failed payment response
            error_message = str(e)
            log_error(PAYMENT, f"Payment failed with error: {error_message}")
            
            # Try to extract payment hash from the parsed invoice if available
            payment_hash = ""
            asset_amount = 0
            asset_id = ""
            try:
                # If we've parsed the invoice, use its details
                if 'parsed_invoice' in locals():
                    payment_hash = parsed_invoice.payment_hash
                    asset_amount = parsed_invoice.amount
                    asset_id = parsed_invoice.asset_id or ""
            except Exception:
                pass
            
            # Return a failed payment response
            return PaymentResponse(
                success=False,
                payment_hash=payment_hash,
                status="failed",
                error=error_message,
                asset_amount=asset_amount,
                asset_id=asset_id
            )
    
    @classmethod
    async def _process_internal_payment(
        cls,
        data: TaprootPaymentRequest,
        wallet: WalletTypeInfo,
        parsed_invoice: ParsedInvoice
    ) -> PaymentResponse:
        """
        Process an internal payment (between users on the same node).
        
        Args:
            data: The payment request data
            wallet: The wallet information
            parsed_invoice: The parsed invoice data
            
        Returns:
            PaymentResponse: The payment result
        """
        with ErrorContext("process_internal_payment", PAYMENT):
            # Get the invoice to retrieve asset_id
            invoice = await get_invoice_by_payment_hash(parsed_invoice.payment_hash)
            if not invoice:
                log_error(PAYMENT, f"Invoice not found for payment hash: {parsed_invoice.payment_hash}")
                return PaymentResponse(
                    success=False,
                    payment_hash=parsed_invoice.payment_hash,
                    status="failed",
                    error="Invoice not found",
                    asset_amount=parsed_invoice.amount,
                    asset_id=parsed_invoice.asset_id or ""
                )
                
            # Initialize wallet using the factory
            taproot_wallet = await TaprootAssetsFactory.create_wallet(
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id
            )
            
            # Check if this is a self-payment
            is_self = await is_self_payment(parsed_invoice.payment_hash, wallet.wallet.user)
            
            # Create sender information dictionary
            sender_info = {
                "wallet_id": wallet.wallet.id,
                "user_id": wallet.wallet.user,
                "payment_request": data.payment_request,
                "asset_id": data.asset_id  # Pass the client-provided asset_id if available
            }
            
            # Use the unified process_payment_settlement method
            try:
                success, settlement_result = await SettlementService.process_payment_settlement(
                    payment_hash=parsed_invoice.payment_hash,
                    payment_request=data.payment_request,
                    asset_id=invoice.asset_id,
                    asset_amount=invoice.asset_amount,
                    fee_sats=0,  # No fee for internal payments
                    user_id=wallet.wallet.user,
                    wallet_id=wallet.wallet.id,
                    node=taproot_wallet.node,
                    is_internal=True,
                    is_self_payment=is_self,
                    description=invoice.description or "",
                    sender_info=sender_info
                )
                
                if not success:
                    error_msg = f"Failed to settle internal payment: {settlement_result.get('error', 'Unknown error')}"
                    log_error(PAYMENT, error_msg)
                    return PaymentResponse(
                        success=False,
                        payment_hash=parsed_invoice.payment_hash,
                        status="failed",
                        error=error_msg,
                        asset_amount=parsed_invoice.amount,
                        asset_id=parsed_invoice.asset_id or ""
                    )
            except Exception as e:
                error_msg = f"Error during internal payment settlement: {str(e)}"
                log_error(PAYMENT, error_msg)
                return PaymentResponse(
                    success=False,
                    payment_hash=parsed_invoice.payment_hash,
                    status="failed",
                    error=error_msg,
                    asset_amount=parsed_invoice.amount,
                    asset_id=parsed_invoice.asset_id or ""
                )
            
            # Return success response for internal payment
            return PaymentResponse(
                success=True,
                payment_hash=parsed_invoice.payment_hash,
                preimage=settlement_result.get('preimage', ''),
                fee_msat=0,  # No routing fee for internal payment
                sat_fee_paid=0,
                routing_fees_sats=0,
                asset_amount=invoice.asset_amount,
                asset_id=invoice.asset_id,
                description=invoice.description,
                internal_payment=True  # Flag to indicate this was an internal payment
            )
    
    @classmethod
    async def _process_external_payment(
        cls,
        data: TaprootPaymentRequest,
        wallet: WalletTypeInfo,
        parsed_invoice: ParsedInvoice
    ) -> PaymentResponse:
        """
        Process an external payment (to a different node).
        
        Args:
            data: The payment request data
            wallet: The wallet information
            parsed_invoice: The parsed invoice data
            
        Returns:
            PaymentResponse: The payment result
        """
        with ErrorContext("process_external_payment", PAYMENT):
            # Initialize wallet using the factory
            taproot_wallet = await TaprootAssetsFactory.create_wallet(
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id
            )
            
            # Set fee limit
            from ..tapd_settings import taproot_settings
            fee_limit_sats = max(data.fee_limit_sats or taproot_settings.default_sat_fee, 10)
            
            # Determine which asset ID to use
            if data.asset_id:
                log_info(PAYMENT, f"Using client-provided asset_id={data.asset_id}")
                asset_id_to_use = data.asset_id
            elif parsed_invoice.asset_id:
                log_info(PAYMENT, f"Using invoice asset_id={parsed_invoice.asset_id}")
                asset_id_to_use = parsed_invoice.asset_id
            else:
                log_debug(PAYMENT, "No asset ID available from client or invoice")
                asset_id_to_use = None
                
            # Make the payment using the low-level wallet method
            # This only handles the direct node communication
            log_info(PAYMENT, f"Making external payment, fee_limit_sats={fee_limit_sats}")
            payment_result = await taproot_wallet.send_raw_payment(
                payment_request=data.payment_request,
                fee_limit_sats=fee_limit_sats,
                asset_id=asset_id_to_use,
                peer_pubkey=data.peer_pubkey
            )

            # Verify payment success
            if "status" in payment_result and payment_result["status"] != "success":
                error_msg = f"Payment failed: {payment_result.get('error', 'Unknown error')}"
                log_error(PAYMENT, error_msg)
                return PaymentResponse(
                    success=False,
                    payment_hash=payment_result.get("payment_hash", ""),
                    status="failed",
                    error=error_msg,
                    asset_amount=parsed_invoice.amount,
                    asset_id=parsed_invoice.asset_id or ""
                )
                
            # Get payment details
            payment_hash = payment_result.get("payment_hash", "")
            preimage = payment_result.get("payment_preimage", "")
            routing_fees_sats = payment_result.get("fee_sats", 0)
            
            # Use the client-provided asset_id for recording the payment
            asset_id = data.asset_id if data.asset_id else ""
            log_info(PAYMENT, f"Using asset_id={asset_id} for recording payment")
            
            # Extract description from the parsed invoice
            description = parsed_invoice.description if parsed_invoice.description else None
            
            # Use the unified process_payment_settlement method
            # Add a small delay to allow any pending transactions to complete
            await asyncio.sleep(0.5)
            
            success, settlement_result = await SettlementService.process_payment_settlement(
                payment_hash=payment_hash,
                payment_request=data.payment_request,
                asset_id=asset_id,
                asset_amount=parsed_invoice.amount,  # Use the correct asset amount from the invoice
                fee_sats=routing_fees_sats,         # Use the actual fee paid, not the limit
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id,
                description=description,
                preimage=preimage,
                is_internal=False,
                is_self_payment=False
            )
            
            if not success:
                log_warning(PAYMENT, "Payment was successful but failed to record in database")
            
            # Return success response
            return PaymentResponse(
                success=True,
                payment_hash=payment_hash,
                preimage=preimage,
                fee_msat=routing_fees_sats * 1000,  # Convert sats to msats
                sat_fee_paid=0,  # No service fee
                routing_fees_sats=routing_fees_sats,
                asset_amount=parsed_invoice.amount,  # Use the correct asset amount from the invoice
                asset_id=asset_id,
                description=description
            )
    
    @staticmethod
    async def parse_invoice(payment_request: str) -> ParsedInvoice:
        """
        Parse a BOLT11 payment request to extract invoice details.
        
        NOTE: The tapd implementation allows decoding invoices with any asset ID.
        We use the first available asset ID for decoding to extract the amount,
        but the actual payment will use the client-provided asset ID.
        
        Args:
            payment_request: BOLT11 payment request to parse
            
        Returns:
            ParsedInvoice: Parsed invoice data with amount
            
        Raises:
            Exception: If the invoice format is invalid or the asset amount cannot be determined
        """
        with ErrorContext("parse_invoice", API):
            # Use the bolt11 library to decode the invoice
            decoded = bolt11.decode(payment_request)
            
            # Extract the description and initialize variables
            description = decoded.description if hasattr(decoded, "description") else ""
            asset_id = None
            asset_amount = None
            
            try:
                # Get raw assets from AssetService
                from .asset_service import AssetService
                assets = await AssetService.get_raw_assets()
                log_info(API, f"Found {len(assets)} available assets")
                
                # Use the first available asset for decoding
                if assets and len(assets) > 0:
                    asset_id_to_try = assets[0].get("asset_id")
                    if asset_id_to_try:
                        log_info(API, f"Using first available asset_id: {asset_id_to_try} for decoding")
                        
                        # Import the parser client
                        from ..tapd.taproot_parser import TaprootParserClient
                        
                        # Get the singleton parser client instance
                        parser_client = TaprootParserClient.get_instance()
                        
                        # Decode the payment request using the parser client
                        decoded_result = await parser_client.decode_asset_pay_req(
                            asset_id=asset_id_to_try,
                            payment_request=payment_request
                        )
                        
                        # Extract the asset amount
                        if 'asset_amount' in decoded_result:
                            asset_amount = float(decoded_result['asset_amount'])
                            asset_id = asset_id_to_try  # Note: This is just for reference, actual payment will use client-provided asset_id
                            log_info(API, f"Extracted invoice amount={asset_amount} using first available asset")
                        else:
                            raise Exception("Response does not contain asset_amount")
                    else:
                        raise Exception("First asset has no asset_id")
                else:
                    raise Exception("No assets available for decoding invoice")
            except Exception as e:
                log_warning(API, f"Failed to get assets or try them: {str(e)}")
            
            # If we couldn't extract the amount, raise an error
            if asset_amount is None:
                error_msg = "Could not extract asset amount from invoice"
                log_error(API, error_msg)
                raise Exception(error_msg)
            
            # Create and return the parsed invoice
            return ParsedInvoice(
                payment_hash=decoded.payment_hash,
                amount=asset_amount,
                description=description,
                expiry=decoded.expiry if hasattr(decoded, "expiry") else 3600,
                timestamp=decoded.date,
                valid=True,
                asset_id=asset_id
            )
    
    @staticmethod
    async def determine_payment_type(
        payment_hash: str, 
        user_id: str
    ) -> str:
        """
        Determine the type of payment (external, internal, or self).
        
        Args:
            payment_hash: The payment hash to check
            user_id: The current user's ID
            
        Returns:
            str: Payment type - "external", "internal", or "self"
        """
        # Check if this is an internal payment
        is_internal_pay = await is_internal_payment(payment_hash)
        
        if is_internal_pay:
            # Check if this is a self-payment
            is_self_pay = await is_self_payment(payment_hash, user_id)
            return "self" if is_self_pay else "internal"
        
        return "external"
    
    @staticmethod
    async def get_user_payments(user_id: str) -> List[TaprootPayment]:
        """
        Get all Taproot Asset payments for a user.
        
        Args:
            user_id: The user ID
            
        Returns:
            List[TaprootPayment]: List of payments
            
        Raises:
            HTTPException: If there's an error retrieving payments
        """
        try:
            payments = await get_user_payments(user_id)
            return payments
        except Exception as e:
            log_error(PAYMENT, f"Error retrieving payments: {str(e)}")
            raise_http_exception(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve payments: {str(e)}",
            )
