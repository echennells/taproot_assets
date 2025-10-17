import hashlib
import time
from typing import Optional, Dict, Any
import grpc
import grpc.aio
from loguru import logger
from lnbits import bolt11
import re

from .taproot_adapter import (
    taprootassets_pb2,
    tapchannel_pb2,
    lightning_pb2,
    router_pb2,
    invoices_pb2
)

# Import Settlement Service
from ..services.settlement_service import SettlementService

# Import database functions from crud re-exports
from ..crud import (
    get_invoice_by_payment_hash,
    is_internal_payment,
    is_self_payment
)

from ..logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    log_exception, PAYMENT, LogContext
)

class TaprootPaymentManager:
    """
    Handles Taproot Asset payment processing.
    This class is responsible for paying invoices and updating Taproot Assets after payments.
    """

    def __init__(self, node):
        """
        Initialize the payment manager with a reference to the node.

        Args:
            node: The TaprootAssetsNodeExtension instance
        """
        self.node = node

    async def pay_asset_invoice(
        self,
        payment_request: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None,
        peer_pubkey: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Pay a Taproot Asset invoice.

        Args:
            payment_request: The payment request (BOLT11 invoice)
            fee_limit_sats: Optional fee limit in satoshis
            asset_id: Optional asset ID to use for payment
            peer_pubkey: Optional peer public key to specify which channel to use

        Returns:
            Dict with payment details
        """
        with LogContext(PAYMENT, f"paying asset invoice", log_level="info"):
            try:
                log_debug(PAYMENT, f"Paying asset invoice: {payment_request[:30]}...")
                
                # RFQ Debug: Log payment initiation
                log_info(PAYMENT, f"RFQ_DEBUG: Starting RFQ payment process")
                log_info(PAYMENT, f"RFQ_DEBUG: Invoice: {payment_request[:50]}...")
                log_info(PAYMENT, f"RFQ_DEBUG: Asset ID provided: {asset_id}")
                log_info(PAYMENT, f"RFQ_DEBUG: Peer pubkey: {peer_pubkey}")

                # Set default fee limit with minimum for routing
                fee_limit_sats = max(fee_limit_sats or 10, 1)
                log_info(PAYMENT, f"Using fee_limit_sats={fee_limit_sats} for payment")

                # Decode invoice to get payment hash
                try:
                    decoded = bolt11.decode(payment_request)
                    payment_hash = decoded.payment_hash
                    log_info(PAYMENT, f"Payment hash: {payment_hash}")
                except Exception as e:
                    log_error(PAYMENT, f"Failed to decode invoice: {str(e)}")
                    raise Exception(f"Invalid invoice format: {str(e)}")

                # If asset_id is not available, try to get it from available assets
                if not asset_id:
                    try:
                        log_debug(PAYMENT, "Asset ID not provided, checking available assets")
                        assets = await self.node.asset_manager.list_assets()
                        if assets and len(assets) > 0:
                            asset_id = assets[0]["asset_id"]
                            log_debug(PAYMENT, f"Using first available asset: {asset_id}")
                        else:
                            raise Exception("No asset ID provided and no assets available")
                    except Exception as e:
                        log_error(PAYMENT, f"Failed to get assets: {e}")
                        raise Exception("No asset ID provided and failed to get available assets")

                # Verify we have required parameters
                if not payment_hash:
                    raise Exception("Could not extract payment hash from invoice")
                    
                if not asset_id:
                    raise Exception("No asset ID provided or found in invoice")
                
                # Check if this is an internal payment (invoice belongs to any user on this node)
                # This check should be done at the API layer, but we include it here as an additional safety check
                is_internal = await is_internal_payment(payment_hash)
                if is_internal:
                    log_warning(PAYMENT, f"Detected internal payment attempt for hash {payment_hash}. This should be handled by update_after_payment.")
                    raise Exception("Internal payments (to another user on this node) are automatically handled by the standard payment endpoint.")

                # Convert asset ID to bytes
                asset_id_bytes = bytes.fromhex(asset_id)

                # Create the router payment request
                router_payment_request = router_pb2.SendPaymentRequest(
                    payment_request=payment_request,
                    fee_limit_sat=fee_limit_sats,
                    timeout_seconds=30,
                    no_inflight_updates=False
                )

                # Create taproot channel payment request
                request = tapchannel_pb2.SendPaymentRequest(
                    payment_request=router_payment_request,
                    asset_id=asset_id_bytes,
                    allow_overpay=True
                )

                # Add peer_pubkey if provided
                if peer_pubkey:
                    request.peer_pubkey = bytes.fromhex(peer_pubkey)
                    log_info(PAYMENT, f"Using peer_pubkey: {peer_pubkey}")

                # Send payment and process stream responses
                log_info(PAYMENT, f"Sending payment for asset_id={asset_id}")
                log_info(PAYMENT, f"RFQ_DEBUG: Initiating SendPayment gRPC call")
                log_info(PAYMENT, f"RFQ_DEBUG: Payment hash: {payment_hash}")
                log_info(PAYMENT, f"RFQ_DEBUG: Asset ID bytes: {asset_id_bytes.hex()}")
                
                try:
                    response_stream = self.node.tapchannel_stub.SendPayment(request)
                except grpc.aio.AioRpcError as e:
                    log_error(PAYMENT, f"gRPC error starting payment: {e.code()}: {e.details()}")
                    log_error(PAYMENT, f"RFQ_DEBUG: gRPC error details: {e}")
                    raise Exception(f"Failed to start payment: {e.details()}")
                
                # Process the stream responses
                preimage = ""
                fee_msat = 0
                status = "success"  # Default to success unless error occurs
                accepted_sell_order_seen = False
                
                try:
                    async for response in response_stream:
                        # Handle accepted sell order
                        if hasattr(response, 'accepted_sell_order') and response.HasField('accepted_sell_order'):
                            log_info(PAYMENT, "Received accepted sell order response")
                            order = response.accepted_sell_order
                            log_info(PAYMENT, f"RFQ_DEBUG: Accepted sell order received")
                            log_info(PAYMENT, f"RFQ_DEBUG: Order ID: {order.id.hex() if hasattr(order, 'id') else 'unknown'}")
                            log_info(PAYMENT, f"RFQ_DEBUG: Asset amount: {order.asset_amount if hasattr(order, 'asset_amount') else 'unknown'}")
                            log_info(PAYMENT, f"RFQ_DEBUG: Bid price: {order.bid_price if hasattr(order, 'bid_price') else 'unknown'}")
                            log_info(PAYMENT, f"RFQ_DEBUG: Ask price: {order.ask_price if hasattr(order, 'ask_price') else 'unknown'}")
                            accepted_sell_order_seen = True
                            continue
                            
                        # Handle payment result
                        if hasattr(response, 'payment_result') and response.HasField('payment_result'):
                            result = response.payment_result
                            status_code = result.status if hasattr(result, 'status') else -1
                            
                            # Map status code to action
                            if status_code == 2:  # SUCCEEDED
                                if hasattr(result, 'payment_preimage'):
                                    preimage = result.payment_preimage.hex() if isinstance(result.payment_preimage, bytes) else str(result.payment_preimage)
                                
                                if hasattr(result, 'fee_msat'):
                                    fee_msat = result.fee_msat
                                    
                                log_info(PAYMENT, f"Payment succeeded: hash={payment_hash}, fee={fee_msat//1000} sat")
                                
                            elif status_code == 3:  # FAILED
                                status = "failed"
                                failure_reason = result.failure_reason if hasattr(result, 'failure_reason') else "Unknown failure"
                                log_error(PAYMENT, f"Payment failed: {failure_reason}")
                                raise Exception(f"Payment failed: {failure_reason}")
                    
                    # Stream completed without explicit error
                    log_info(PAYMENT, "Payment stream completed")
                    log_info(PAYMENT, f"RFQ_DEBUG: Stream completed - Status: {status}, Preimage: {'yes' if preimage else 'no'}, Accepted order: {accepted_sell_order_seen}")
                    
                    # If we've seen an accepted_sell_order but no final status,
                    # consider it potentially successful
                    if accepted_sell_order_seen and status != "failed":
                        log_info(PAYMENT, "Payment appears to be in progress (saw accepted sell order)")
                        log_warning(PAYMENT, "RFQ_DEBUG: WARNING - RFQ order accepted but no final payment status received!")
                        status = "success"
                    
                except grpc.aio.AioRpcError as e:
                    # Check if the error indicates payment in progress
                    error_str = e.details().lower()
                    if any(msg in error_str for msg in ["payment initiated", "in progress", "in flight"]):
                        log_info(PAYMENT, "Payment appears to be in progress, treating as potentially successful")
                        status = "success"
                    elif "self-payments not allowed" in error_str:
                        # Catch the self-payment error specifically
                        log_warning(PAYMENT, f"Self-payment detected for {payment_hash} - this should be handled by update_after_payment")
                        raise Exception("Self-payments are not allowed through the regular payment flow. They are automatically handled by the standard payment endpoint.")
                    else:
                        log_error(PAYMENT, f"gRPC error in payment stream: {e.code()}: {e.details()}")
                        raise Exception(f"Payment error: {e.details()}")
                except Exception as e:
                    error_str = str(e).lower()
                    
                    # Check for specific error codes or messages
                    if "payment failed: 2" in error_str:
                        # Error code 2 indicates insufficient channel balance (sats)
                        log_error(PAYMENT, f"Payment failed due to insufficient channel balance: {str(e)}")
                        status = "failed"
                        raise Exception("Failed - Insufficient sats balance in channel")
                    elif "payment failed: 5" in error_str:
                        # Error code 5 indicates liquidity/routing issues (usually inbound liquidity)
                        log_error(PAYMENT, f"Payment failed due to liquidity problem: {str(e)}")
                        status = "failed"
                        raise Exception("Payment Failed: Liquidity Problem")
                    elif "insufficient balance" in error_str or "no asset channel balance" in error_str:
                        # Other balance-related errors
                        log_error(PAYMENT, f"Payment failed due to insufficient balance: {str(e)}")
                        status = "failed"
                        raise Exception("Payment failed: Insufficient balance")
                    elif accepted_sell_order_seen and "timeout" in error_str:
                        # Timeout after accepted_sell_order might still succeed
                        log_info(PAYMENT, f"Payment stream ended with timeout after accepted_sell_order: {str(e)}")
                        log_info(PAYMENT, "Considering payment as potentially successful")
                        status = "success"
                    elif accepted_sell_order_seen:
                        # For other errors after accepted_sell_order, mark as failed
                        log_error(PAYMENT, f"Payment failed after accepted_sell_order: {str(e)}")
                        status = "failed"
                        raise Exception(f"Payment failed: {str(e)}")
                    else:
                        # General error handling
                        log_error(PAYMENT, f"Error in payment stream: {str(e)}")
                        status = "failed"
                        raise Exception(f"Payment error: {str(e)}")
                
                # Get the asset amount from decoded invoice
                asset_amount = decoded.amount_msat // 1000 if hasattr(decoded, "amount_msat") else 0
                
                # We're NOT recording the payment here anymore - this will be handled by the PaymentService
                # This fixes the issue with the duplicate payment records
                
                # RFQ Debug: Final summary
                log_info(PAYMENT, f"RFQ_DEBUG: Payment completed - Hash: {payment_hash}, Status: {status}")
                log_info(PAYMENT, f"RFQ_DEBUG: Asset: {asset_id}, Amount: {asset_amount}, Fee: {fee_msat // 1000} sats")
                log_info(PAYMENT, f"RFQ_DEBUG: Preimage present: {'yes' if preimage else 'no'}")
                
                # Return response with all available information
                return {
                    "payment_hash": payment_hash,
                    "payment_preimage": preimage,
                    "fee_sats": fee_msat // 1000,
                    "status": status,
                    "payment_request": payment_request,
                    "asset_id": asset_id,
                    "asset_amount": asset_amount
                }

            except grpc.aio.AioRpcError as e:
                log_error(PAYMENT, f"gRPC error in pay_asset_invoice: {e.code()}: {e.details()}")
                
                # Create user-friendly error message
                error_details = e.details().lower()
                if "multiple asset channels found" in error_details:
                    detail = "Multiple channels found for this asset. Please select a specific channel."
                elif "no asset channel balance found" in error_details:
                    detail = "Insufficient channel balance for this asset."
                else:
                    detail = f"gRPC error: {e.details()}"
                    
                raise Exception(detail)
                
            except Exception as e:
                log_error(PAYMENT, f"Payment failed: {str(e)}")
                raise Exception(f"Failed to pay Taproot Asset invoice: {str(e)}")

    async def update_after_payment(
        self,
        payment_request: str,
        payment_hash: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update Taproot Assets after a payment has been made through the LNbits wallet.

        This method is specifically used for internal payments (including self-payments) to update 
        the Taproot Assets daemon about internal transfers without requiring an actual
        Lightning Network payment.

        Args:
            payment_request: The original BOLT11 invoice
            payment_hash: The payment hash of the completed payment
            fee_limit_sats: Optional fee limit in satoshis (not used for actual payment now)
            asset_id: Optional asset ID to use for the update

        Returns:
            Dict containing the update confirmation
        """
        with LogContext(PAYMENT, f"updating after payment {payment_hash[:8]}...", log_level="info"):
            try:
                log_info(PAYMENT, f"=== INTERNAL PAYMENT PROCESS STARTING ===")
                log_info(PAYMENT, f"Payment hash: {payment_hash}")
                log_info(PAYMENT, f"Asset ID: {asset_id or 'Not specified'}")

                # Get the wallet information from the node
                if not hasattr(self.node, 'wallet') or not self.node.wallet:
                    log_error(PAYMENT, "Node has no wallet information")
                    raise Exception("Wallet information missing from node")
                
                # Import PaymentService to use the strategy pattern
                from ..services.payment_service import PaymentService
                from ..models import TaprootPaymentRequest
                from lnbits.core.models import WalletTypeInfo
                
                # Create wallet info object
                wallet_info = WalletTypeInfo(
                    wallet=self.node.wallet,
                    wallet_type="taproot"
                )
                
                # Create payment request object
                payment_data = TaprootPaymentRequest(
                    payment_request=payment_request,
                    fee_limit_sats=fee_limit_sats or 0,
                    asset_id=asset_id
                )
                
                # Process the payment using the PaymentService with forced internal type
                payment_response = await PaymentService.process_payment(
                    data=payment_data,
                    wallet=wallet_info,
                    force_payment_type="internal"
                )
                
                if not payment_response.success:
                    log_error(PAYMENT, f"Failed to process internal payment: {payment_response.error}")
                    raise Exception(f"Failed to process internal payment: {payment_response.error}")
                
                log_info(PAYMENT, "=== INTERNAL PAYMENT COMPLETED SUCCESSFULLY ===")
                
                # Convert PaymentResponse to dictionary format for API compatibility
                response = {
                    "success": True,
                    "payment_hash": payment_response.payment_hash,
                    "message": "Internal payment processed successfully",
                    "preimage": payment_response.preimage or "",
                    "asset_id": payment_response.asset_id,
                    "asset_amount": payment_response.asset_amount,
                    "internal_payment": True
                }
                
                return response

            except Exception as e:
                log_error(PAYMENT, f"Failed to process internal payment: {str(e)}")
                raise Exception(f"Failed to update Taproot Assets: {str(e)}")
