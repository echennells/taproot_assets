"""
Invoice service for Taproot Assets extension.
Handles invoice-related business logic.
"""
from typing import Dict, Any, Optional, List, Tuple, Union
from http import HTTPStatus
from loguru import logger

from lnbits.core.models import WalletTypeInfo, User

from ..models import TaprootInvoiceRequest, InvoiceResponse, TaprootInvoice
from ..tapd.taproot_factory import TaprootAssetsFactory
from ..error_utils import raise_http_exception, ErrorContext
from ..logging_utils import API
# Import from crud re-exports
from ..crud import (
    create_invoice,
    get_invoice,
    get_invoice_by_payment_hash,
    get_user_invoices
)
from .notification_service import NotificationService
from .settlement_service import SettlementService
from ..tapd_settings import taproot_settings


class InvoiceService:
    """
    Service for handling Taproot Asset invoices.
    This service encapsulates invoice-related business logic.
    """
    
    @staticmethod
    async def create_invoice(
        data: TaprootInvoiceRequest,
        user_id: str,
        wallet_id: str
    ) -> InvoiceResponse:
        """
        Create an invoice for a Taproot Asset.
        
        Args:
            data: The invoice request data
            user_id: The user ID
            wallet_id: The wallet ID
            
        Returns:
            InvoiceResponse: The created invoice
            
        Raises:
            HTTPException: If invoice creation fails
        """
        logger.info(f"Creating invoice for asset_id={data.asset_id}, amount={data.amount}")
        with ErrorContext("create_invoice", API):
            # Create a wallet instance using the factory
            taproot_wallet = await TaprootAssetsFactory.create_wallet(
                user_id=user_id,
                wallet_id=wallet_id
            )
            
            # Add detailed logging before creating invoice
            logger.info(f"[{API}] Creating raw invoice with: asset_id={data.asset_id}, amount={data.amount}, peer={data.peer_pubkey}")
            
            # If no peer specified, find one with an asset channel
            peer_pubkey = data.peer_pubkey
            if peer_pubkey is None:
                logger.info(f"[{API}] No peer specified, looking for available asset channels")
                
                # Use our own AssetService to find the peer
                from .asset_service import AssetService
                from lnbits.core.models import WalletTypeInfo, Wallet
                
                # Create wallet info for asset lookup
                from lnbits.core.models.wallets import KeyType
                wallet_obj = Wallet(id=wallet_id, user=user_id, adminkey="", inkey="", balance_msat=0, name="")
                wallet_info = WalletTypeInfo(key_type=KeyType.admin, wallet=wallet_obj)
                
                # Get user's assets
                assets = await AssetService.list_assets(wallet_info)
                
                # Find the asset with an active channel
                for asset in assets:
                    if asset.get("asset_id") == data.asset_id and asset.get("channel_info") and asset["channel_info"].get("peer_pubkey"):
                        # Skip inactive channels
                        if not asset["channel_info"].get("active", True):
                            logger.info(f"[{API}] Skipping inactive channel")
                            continue
                        
                        peer_pubkey = asset["channel_info"]["peer_pubkey"]
                        logger.info(f"[{API}] Found active asset channel with peer {peer_pubkey[:16]}...")
                        break
                
                if peer_pubkey is None:
                    raise_http_exception(
                        status_code=HTTPStatus.BAD_REQUEST,
                        detail=f"No channel found for asset {data.asset_id}. Please open a channel with this asset first."
                    )
            
            # Get raw node invoice using the wallet's low-level method
            invoice_result = await taproot_wallet.get_raw_node_invoice(
                description=data.description or "",
                asset_id=data.asset_id,
                asset_amount=data.amount,
                expiry=data.expiry,
                peer_pubkey=peer_pubkey
            )
            
            # Log the result
            logger.info(f"[{API}] Raw invoice result: {invoice_result}")

            if not invoice_result or "invoice_result" not in invoice_result:
                raise_http_exception(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    detail=f"Failed to create invoice: Invalid response from node"
                )

            # Extract payment details
            payment_hash = invoice_result["invoice_result"]["r_hash"]
            payment_request = invoice_result["invoice_result"]["payment_request"]
            
            # Get satoshi fee from settings
            satoshi_amount = taproot_settings.default_sat_fee

            # Import transaction context manager
            from ..db_utils import transaction
            
            # Create invoice record within a transaction
            invoice = None
            async with transaction(max_retries=3, retry_delay=0.2) as conn:
                invoice = await create_invoice(
                    asset_id=data.asset_id,
                    asset_amount=data.amount,
                    satoshi_amount=satoshi_amount,
                    payment_hash=payment_hash,
                    payment_request=payment_request,
                    user_id=user_id,
                    wallet_id=wallet_id,
                    description=data.description or "",
                    expiry=data.expiry,
                    extra=data.extra,
                    conn=conn
                )

            # Send WebSocket notification for new invoice AFTER the transaction is committed
            if invoice:
                try:
                    invoice_data = {
                        "id": invoice.id,
                        "payment_hash": payment_hash,
                        "payment_request": payment_request,
                        "asset_id": data.asset_id,
                        "asset_amount": data.amount,
                        "satoshi_amount": satoshi_amount,
                        "description": invoice.description,
                        "status": "pending",
                        "created_at": invoice.created_at.isoformat() if hasattr(invoice.created_at, "isoformat") else str(invoice.created_at)
                    }
                    
                    # Use NotificationService for WebSocket notification
                    notification_sent = await NotificationService.notify_invoice_update(user_id, invoice_data)
                    if not notification_sent:
                        logger.warning(f"Failed to send WebSocket notification for invoice {invoice.id}")
                except Exception as e:
                    # Don't fail the whole operation if notification fails
                    logger.warning(f"Failed to send notification for invoice {invoice.id}: {str(e)}")

            # Return response
            return InvoiceResponse(
                payment_hash=payment_hash,
                payment_request=payment_request,
                asset_id=data.asset_id,
                asset_amount=data.amount,
                satoshi_amount=satoshi_amount,
                checking_id=invoice.id,
            )
    
    @staticmethod
    async def get_invoice(invoice_id: str, user_id: str) -> TaprootInvoice:
        """
        Get a specific Taproot Asset invoice by ID.
        
        Args:
            invoice_id: The invoice ID
            user_id: The user ID
            
        Returns:
            TaprootInvoice: The invoice
            
        Raises:
            HTTPException: If the invoice is not found or doesn't belong to the user
        """
        with ErrorContext("get_invoice", API):
            invoice = await get_invoice(invoice_id)

            if not invoice:
                raise_http_exception(
                    status_code=HTTPStatus.NOT_FOUND,
                    detail="Invoice not found",
                )

            if invoice.user_id != user_id:
                raise_http_exception(
                    status_code=HTTPStatus.FORBIDDEN,
                    detail="Not your invoice",
                )

            return invoice
    
    @staticmethod
    async def get_user_invoices(user_id: str) -> List[TaprootInvoice]:
        """
        Get all Taproot Asset invoices for a user.
        
        Args:
            user_id: The user ID
            
        Returns:
            List[TaprootInvoice]: List of invoices
            
        Raises:
            HTTPException: If there's an error retrieving invoices
        """
        with ErrorContext("get_user_invoices", API):
            invoices = await get_user_invoices(user_id)
            return invoices
    
    @staticmethod
    async def update_invoice_status(
        invoice_id: str,
        status: str,
        user_id: str,
        wallet_id: str
    ) -> TaprootInvoice:
        """
        Update the status of a Taproot Asset invoice.
        
        Args:
            invoice_id: The invoice ID
            status: The new status
            user_id: The user ID
            wallet_id: The wallet ID
            
        Returns:
            TaprootInvoice: The updated invoice
            
        Raises:
            HTTPException: If the invoice is not found, doesn't belong to the user, or the status is invalid
        """
        with ErrorContext("update_invoice_status", API):
            invoice = await get_invoice(invoice_id)

            if not invoice:
                raise_http_exception(
                    status_code=HTTPStatus.NOT_FOUND,
                    detail="Invoice not found",
                )

            if invoice.user_id != user_id:
                raise_http_exception(
                    status_code=HTTPStatus.FORBIDDEN,
                    detail="Not your invoice",
                )

            if status not in ["pending", "paid", "expired", "cancelled"]:
                raise_http_exception(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="Invalid status",
                )

            # If marking as paid, use SettlementService to handle it correctly
            if status == "paid" and invoice.status != "paid":
                # Initialize a wallet instance to get the node
                taproot_wallet = await TaprootAssetsFactory.create_wallet(
                    user_id=user_id,
                    wallet_id=wallet_id
                )
                
                # Use SettlementService to settle the invoice
                is_internal = True  # This would typically be an internal update
                is_self_payment = False  # Default for API updates
                
                success, result = await SettlementService.settle_invoice(
                    payment_hash=invoice.payment_hash,
                    node=taproot_wallet.node,
                    is_internal=is_internal,
                    is_self_payment=is_self_payment,
                    user_id=user_id,
                    wallet_id=wallet_id
                )
                
                if success:
                    logger.info(f"Invoice {invoice_id} was settled successfully via SettlementService")
                    # The settlement service will have already updated the invoice status
                    return await get_invoice(invoice_id)  # Get the updated invoice
                else:
                    logger.error(f"Failed to settle invoice {invoice_id}: {result.get('error', 'Unknown error')}")
                    raise_http_exception(
                        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                        detail=f"Failed to settle invoice: {result.get('error', 'Unknown error')}",
                    )
            else:
                # For non-payment status updates, use the regular update method
                from ..crud import update_invoice_status as db_update_invoice_status
                updated_invoice = await db_update_invoice_status(invoice_id, status)
                
                # Send WebSocket notification about status update using NotificationService
                if updated_invoice:
                    invoice_data = {
                        "id": updated_invoice.id,
                        "payment_hash": updated_invoice.payment_hash,
                        "status": updated_invoice.status,
                        "asset_id": updated_invoice.asset_id,
                        "asset_amount": updated_invoice.asset_amount
                    }
                    await NotificationService.notify_invoice_update(user_id, invoice_data)
                
                return updated_invoice
