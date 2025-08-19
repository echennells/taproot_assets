import os
import time
import hashlib
import asyncio
from typing import Optional, Dict, Any, List
import grpc
import grpc.aio
import json
import base64
from lnbits import bolt11
from lnbits.nodes.base import Node
from lnbits.db import Filters, Page
from lnbits.nodes.base import (
    NodeChannel, NodePeerInfo, NodeInfoResponse, NodeInvoice, 
    NodePayment, NodeInvoiceFilters, NodePaymentsFilters, ChannelPoint
)
from lnbits.utils.cache import cache

# Import the adapter module for Taproot Asset gRPC interfaces
from .taproot_adapter import (
    taprootassets_pb2,
    rfq_pb2,
    rfq_pb2_grpc,
    tapchannel_pb2,
    lightning_pb2,
    invoices_pb2,
    create_taprootassets_client,
    create_tapchannel_client,
    create_lightning_client,
    create_invoices_client
)

# Import the manager modules
from .taproot_assets import TaprootAssetManager
from .taproot_invoices import TaprootInvoiceManager
from .taproot_payments import TaprootPaymentManager
from .taproot_transfers import TaprootTransferManager

# Import settlement service
from ..services.settlement_service import SettlementService

# Import logging utilities
from ..logging_utils import (
    log_debug, log_info, log_warning, log_error, 
    log_exception, NODE, LogContext
)
from ..error_utils import ErrorContext, TaprootAssetError

class TaprootAssetsNodeExtension(Node):
    """
    Implementation of Taproot Assets node functionality for the extension.
    This mirrors the core TaprootAssetsNode class.
    """
    # Cache expiry times in seconds
    PREIMAGE_CACHE_EXPIRY = 86400  # 24 hours
    ASSET_ID_CACHE_EXPIRY = 86400  # 24 hours

    def _store_preimage(self, payment_hash: str, preimage: str):
        """Store a preimage for a given payment hash."""
        cache.set(f"taproot:preimage:{payment_hash}", preimage, expiry=self.PREIMAGE_CACHE_EXPIRY)
        log_debug(NODE, f"Stored preimage for payment hash: {payment_hash[:8]}...")

    def _store_asset_id(self, payment_hash: str, asset_id: str):
        """
        Store an asset_id for a given payment hash.
        
        Args:
            payment_hash: The payment hash
            asset_id: The asset_id corresponding to the payment hash
        """
        cache.set(f"taproot:asset_id:{payment_hash}", asset_id, expiry=self.ASSET_ID_CACHE_EXPIRY)
        log_debug(NODE, f"Stored asset_id {asset_id[:8]}... for payment hash: {payment_hash[:8]}...")

    def _get_asset_id(self, payment_hash: str) -> Optional[str]:
        """
        Retrieve an asset_id for a given payment hash.
        
        Args:
            payment_hash: The payment hash to look up
            
        Returns:
            str: The asset_id if found, None otherwise
        """
        asset_id = cache.get(f"taproot:asset_id:{payment_hash}")
        if asset_id:
            log_debug(NODE, f"Found asset_id {asset_id[:8]}... for payment hash: {payment_hash[:8]}...")
        else:
            log_debug(NODE, f"No asset_id found for payment hash: {payment_hash[:8]}...")
        return asset_id

    def _get_preimage(self, payment_hash: str) -> Optional[str]:
        """Retrieve a preimage for a given payment hash."""
        preimage = cache.get(f"taproot:preimage:{payment_hash}")
        if preimage:
            log_debug(NODE, f"Found preimage for payment hash: {payment_hash[:8]}...")
        else:
            log_debug(NODE, f"No preimage found for payment hash: {payment_hash[:8]}...")
        return preimage

    def __init__(
        self,
        wallet,  # Now required as in the base Node class
        host: str = None,
        network: str = None,
        tls_cert_path: str = None,
        macaroon_path: str = None,
        ln_macaroon_path: str = None,
        ln_macaroon_hex: str = None,
        tapd_macaroon_hex: str = None,
    ):
        from ..tapd_settings import taproot_settings
        from lnbits.settings import settings as lnbits_settings

        # Initialize the base Node class
        super().__init__(wallet)
        
        # Initialize node
        
        # Determine if we should try litd integrated mode
        self.use_litd_integrated = False
        self.is_standalone_tapd = taproot_settings.has_standalone_config
        
        if not self.is_standalone_tapd:
            # Try to use LND settings for litd integrated mode
            self._try_litd_integrated_mode(lnbits_settings)
        
        if not self.use_litd_integrated:
            # Use standalone tapd configuration
            self.host = host or taproot_settings.tapd_host
            self.network = network or taproot_settings.tapd_network

            # Get paths from settings if not provided
            tls_cert_path = tls_cert_path or taproot_settings.tapd_tls_cert_path
            macaroon_path = macaroon_path or taproot_settings.tapd_macaroon_path
            ln_macaroon_path = ln_macaroon_path or taproot_settings.lnd_macaroon_path
            tapd_macaroon_hex = tapd_macaroon_hex or taproot_settings.tapd_macaroon_hex
            ln_macaroon_hex = ln_macaroon_hex or taproot_settings.lnd_macaroon_hex
            
            # Read credentials for standalone mode
            self._read_standalone_credentials(
                tls_cert_path, macaroon_path, ln_macaroon_path,
                tapd_macaroon_hex, ln_macaroon_hex
            )

        # Setup gRPC credentials
        # Setup gRPC credentials for Taproot
        self.credentials = grpc.ssl_channel_credentials(self.cert)
        self.auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", self.macaroon)], None)
        )
        self.combined_creds = grpc.composite_channel_credentials(
            self.credentials, self.auth_creds
        )

        # Setup gRPC credentials for Lightning
        self.ln_auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", self.ln_macaroon)], None)
        )
        self.ln_combined_creds = grpc.composite_channel_credentials(
            self.credentials, self.ln_auth_creds
        )

        # Create gRPC channels
        # Create gRPC channels
        self.channel = grpc.aio.secure_channel(self.host, self.combined_creds)
        
        self.stub = create_taprootassets_client(self.channel)

        # Create Lightning gRPC channel
        self.ln_channel = grpc.aio.secure_channel(self.host, self.ln_combined_creds)
        self.ln_stub = create_lightning_client(self.ln_channel)
        self.invoices_stub = create_invoices_client(self.ln_channel)

        # Create TaprootAssetChannels gRPC channel
        self.tap_channel = grpc.aio.secure_channel(self.host, self.combined_creds)
        self.tapchannel_stub = create_tapchannel_client(self.tap_channel)

        # Initialize managers
        # Initialize managers
        self.asset_manager = TaprootAssetManager(self)
        self.invoice_manager = TaprootInvoiceManager(self)
        self.payment_manager = TaprootPaymentManager(self)
        # Use the singleton pattern for TaprootTransferManager
        self.transfer_manager = TaprootTransferManager.get_instance(self)
        
        # Note: Asset transfer monitoring has been removed as it was not fully implemented
        # All connections initialized
    
    def _try_litd_integrated_mode(self, lnbits_settings):
        """Try to configure for litd integrated mode using LNbits LND settings."""
        try:
            # Check if we have LND settings configured (either gRPC or REST)
            lnd_endpoint = None
            cert_path = None
            
            # First check for gRPC settings
            if hasattr(lnbits_settings, 'lnd_grpc_endpoint') and lnbits_settings.lnd_grpc_endpoint:
                log_info(NODE, "Attempting to use litd integrated mode via LND gRPC settings")
                lnd_endpoint = lnbits_settings.lnd_grpc_endpoint
                self.host = f"{lnd_endpoint}:{getattr(lnbits_settings, 'lnd_grpc_port', 10009)}"
                cert_path = getattr(lnbits_settings, 'lnd_grpc_cert', None) or getattr(lnbits_settings, 'lnd_cert', None)
                
            # Also check for REST settings that might indicate litd
            elif hasattr(lnbits_settings, 'lnd_rest_endpoint') and lnbits_settings.lnd_rest_endpoint:
                # Extract host from REST endpoint (e.g., "https://lit:8080" -> "lit")
                import re
                match = re.match(r'https?://([^:]+)', lnbits_settings.lnd_rest_endpoint)
                if match:
                    host = match.group(1)
                    log_info(NODE, f"Detected LND REST endpoint, checking if litd at {host}:10009")
                    # For litd, tapd is always on port 10009 (gRPC)
                    self.host = f"{host}:10009"
                    cert_path = getattr(lnbits_settings, 'lnd_rest_cert', None)
                    lnd_endpoint = host
                
            if lnd_endpoint and cert_path:
                self.network = "mainnet"  # Will be determined from node info
                
                # Try to use the certificate
                if cert_path and os.path.exists(cert_path):
                    with open(cert_path, 'rb') as f:
                        self.cert = f.read()
                    
                    # Load LND macaroon for LND operations
                    from lnbits.wallets.macaroon import load_macaroon
                    lnd_macaroon = (
                        getattr(lnbits_settings, 'lnd_grpc_macaroon', None)
                        or getattr(lnbits_settings, 'lnd_grpc_admin_macaroon', None)
                        or getattr(lnbits_settings, 'lnd_rest_macaroon', None)
                        or getattr(lnbits_settings, 'lnd_admin_macaroon', None)
                    )
                    encrypted_macaroon = getattr(lnbits_settings, 'lnd_grpc_macaroon_encrypted', None)
                    
                    if lnd_macaroon:
                        lnd_macaroon_bytes = load_macaroon(lnd_macaroon, encrypted_macaroon)
                        # Process LND macaroon
                        if isinstance(lnd_macaroon_bytes, bytes):
                            self.ln_macaroon = lnd_macaroon_bytes.hex()
                        else:
                            self.ln_macaroon = lnd_macaroon_bytes
                        
                        # For litd integrated mode, tapd macaroon must be explicitly configured
                        from ..tapd_settings import taproot_settings
                        tapd_macaroon_path = taproot_settings.tapd_macaroon_path
                        tapd_macaroon_hex = taproot_settings.tapd_macaroon_hex
                        
                        if tapd_macaroon_hex:
                            # Use hex macaroon if provided
                            self.macaroon = tapd_macaroon_hex
                            log_info(NODE, "Using TAPD_MACAROON_HEX for tapd authentication")
                        elif tapd_macaroon_path and os.path.exists(tapd_macaroon_path):
                            # Use tapd macaroon from specified path
                            with open(tapd_macaroon_path, 'rb') as f:
                                self.macaroon = f.read().hex()
                            log_info(NODE, f"Using tapd macaroon from {tapd_macaroon_path}")
                        else:
                            # No tapd macaroon configured for integrated mode
                            log_error(NODE, "litd integrated mode detected but TAPD_MACAROON_PATH not set")
                            raise TaprootAssetError(
                                "litd integrated mode requires TAPD_MACAROON_PATH\n\n"
                                "When using litd (Lightning Terminal), you must set:\n"
                                "  TAPD_MACAROON_PATH=/path/to/.tapd/data/[network]/admin.macaroon\n\n"
                                "Example for Docker:\n"
                                "  TAPD_MACAROON_PATH=/root/.tapd/data/mainnet/admin.macaroon"
                            )
                        
                        self.use_litd_integrated = True
                        log_info(NODE, f"Configured for litd integrated mode at {self.host}")
                        return
        except Exception as e:
            log_warning(NODE, f"Could not configure litd integrated mode: {e}")
        
        # If we get here, litd integrated mode failed
        self.use_litd_integrated = False
    
    def _read_standalone_credentials(self, tls_cert_path, macaroon_path, 
                                   ln_macaroon_path, tapd_macaroon_hex, ln_macaroon_hex):
        """Read credentials for standalone tapd mode."""
        if not tls_cert_path or not (macaroon_path or tapd_macaroon_hex):
            raise TaprootAssetError(
                "Failed to connect to Taproot Assets daemon\n\n"
                "No valid configuration found. Please provide either:\n\n"
                "1. For litd integrated mode:\n"
                "   - Ensure LNbits is configured with gRPC (not REST) to auto-detect litd\n"
                "   - OR set TAPD_MODE=integrated with proper TAPD_* variables\n\n"
                "2. For standalone tapd mode:\n"
                "   - Set environment variables: TAPD_HOST, TAPD_TLS_CERT_PATH, TAPD_MACAROON_PATH\n"
                "   - OR create taproot_assets.conf from the example file\n\n"
                "See documentation for setup instructions."
            )
        
        # Read TLS certificate
        try:
            # Read TLS certificate
            with open(tls_cert_path, 'rb') as f:
                self.cert = f.read()
            # Certificate loaded
        except Exception as e:
            log_error(NODE, f"Failed to read TLS cert from {tls_cert_path}: {str(e)}")
            raise TaprootAssetError(
                f"Failed to read TLS certificate from {tls_cert_path}\n\n"
                f"Error: {str(e)}\n\n"
                "Please check your taproot_assets.conf file and ensure:\n"
                "- TAPD_TLS_CERT_PATH points to a valid TLS certificate\n"
                "- You have read permissions for the certificate file\n"
                "- tapd is running and accessible at the configured host"
            )

        # Read Taproot macaroon
        if tapd_macaroon_hex:
            # Use hex macaroon
            self.macaroon = tapd_macaroon_hex
        else:
            try:
                # Read macaroon file
                with open(macaroon_path, 'rb') as f:
                    self.macaroon = f.read().hex()
                # Macaroon loaded
            except Exception as e:
                log_error(NODE, f"Failed to read Taproot macaroon from {macaroon_path}: {str(e)}")
                raise TaprootAssetError(
                    f"Failed to read Taproot macaroon from {macaroon_path}\n\n"
                    f"Error: {str(e)}\n\n"
                    "Please check your taproot_assets.conf file and ensure:\n"
                    "- TAPD_MACAROON_PATH points to a valid macaroon file\n"
                    "- You have read permissions for the macaroon file"
                )

        # Read Lightning macaroon
        if ln_macaroon_hex:
            # Use hex macaroon
            self.ln_macaroon = ln_macaroon_hex
        else:
            try:
                # Read macaroon file
                with open(ln_macaroon_path, 'rb') as f:
                    self.ln_macaroon = f.read().hex()
                # Macaroon loaded
            except Exception as e:
                log_error(NODE, f"Failed to read Lightning macaroon from {ln_macaroon_path}: {str(e)}")
                raise TaprootAssetError(
                    f"Failed to read Lightning macaroon from {ln_macaroon_path}\n\n"
                    f"Error: {str(e)}\n\n"
                    "Please check your taproot_assets.conf file and ensure:\n"
                    "- LND_REST_MACAROON points to a valid macaroon file\n"
                    "- You have read permissions for the macaroon file"
                )

    def _protobuf_to_dict(self, pb_obj):
        """Convert a protobuf object to a JSON-serializable dict."""
        if pb_obj is None:
            return None

        result = {}
        for field_name in pb_obj.DESCRIPTOR.fields_by_name:
            value = getattr(pb_obj, field_name)
            
            # Convert bytes to hex strings
            if isinstance(value, bytes):
                result[field_name] = value.hex()
            # Handle nested messages
            elif hasattr(value, 'DESCRIPTOR'):
                nested_dict = self._protobuf_to_dict(value)
                if nested_dict is not None:
                    result[field_name] = nested_dict
            # Handle lists
            elif isinstance(value, (list, tuple)):
                result[field_name] = [
                    self._protobuf_to_dict(item) if hasattr(item, 'DESCRIPTOR') else item
                    for item in value
                ]
            # Handle large integers
            elif isinstance(value, int) and value > 2**53 - 1:
                result[field_name] = str(value)
            # Special handling for active status in channel
            elif field_name == 'active':
                # Make sure active status is explicitly set to True or False
                result[field_name] = bool(value)
            # Handle other values
            else:
                result[field_name] = value
                
        return result

    # Required abstract methods from Node base class
    async def _get_id(self) -> str:
        """Get the node ID."""
        # Placeholder implementation
        return "taproot-assets-node"

    async def get_peer_ids(self) -> List[str]:
        """Get peer IDs."""
        # Placeholder implementation
        return []

    async def connect_peer(self, uri: str):
        """Connect to a peer."""
        # Placeholder implementation
        pass

    async def disconnect_peer(self, peer_id: str):
        """Disconnect from a peer."""
        # Placeholder implementation
        pass

    async def _get_peer_info(self, peer_id: str) -> NodePeerInfo:
        """Get peer information."""
        # Placeholder implementation
        return NodePeerInfo(id=peer_id)

    async def open_channel(
        self,
        peer_id: str,
        local_amount: int,
        push_amount: int | None = None,
        fee_rate: int | None = None,
    ) -> ChannelPoint:
        """Open a channel."""
        # Placeholder implementation
        raise NotImplementedError("open_channel not implemented")

    async def close_channel(
        self,
        short_id: str | None = None,
        point: ChannelPoint | None = None,
        force: bool = False,
    ):
        """Close a channel."""
        # Placeholder implementation
        raise NotImplementedError("close_channel not implemented")

    async def get_channel(self, channel_id: str) -> NodeChannel | None:
        """Get a channel."""
        # Placeholder implementation
        return None

    async def get_channels(self) -> List[NodeChannel]:
        """Get all channels."""
        # Placeholder implementation
        return []

    async def set_channel_fee(self, channel_id: str, base_msat: int, ppm: int):
        """Set channel fee."""
        # Placeholder implementation
        raise NotImplementedError("set_channel_fee not implemented")

    async def get_info(self) -> NodeInfoResponse:
        """Get node information."""
        # Placeholder implementation
        raise NotImplementedError("get_info not implemented")

    async def get_payments(
        self, filters: Filters[NodePaymentsFilters]
    ) -> Page[NodePayment]:
        """Get payments."""
        # Placeholder implementation
        return Page(data=[], total=0)

    async def get_invoices(
        self, filters: Filters[NodeInvoiceFilters]
    ) -> Page[NodeInvoice]:
        """Get invoices."""
        # Placeholder implementation
        return Page(data=[], total=0)

    # Delegate methods to the appropriate managers
    async def list_assets(self, force_refresh=False) -> List[Dict[str, Any]]:
        """
        List all Taproot Assets by delegating to the asset manager.
        
        Note: This is a low-level method. For application use, prefer:
        - AssetService.list_assets() when user context is available
        - AssetService.get_raw_assets() when no user context is needed
        
        Args:
            force_refresh: Whether to force a refresh from the node
            
        Returns:
            List[Dict[str, Any]]: List of assets
        """
        with LogContext(NODE, "listing assets", log_level="debug"):
            return await self.asset_manager.list_assets(force_refresh=force_refresh)

    async def list_channel_assets(self, force_refresh=False) -> List[Dict[str, Any]]:
        """
        List all Lightning channels with Taproot Assets.
        
        Args:
            force_refresh: Whether to force a refresh from the node
            
        Returns:
            List[Dict[str, Any]]: List of channel assets
        """
        with LogContext(NODE, "listing channel assets", log_level="debug"):
            return await self.asset_manager.list_channel_assets(force_refresh=force_refresh)

    async def create_asset_invoice(
        self,
        description: str,
        asset_id: str,
        asset_amount: int,
        expiry: Optional[int] = None,
        peer_pubkey: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create an invoice for a Taproot Asset transfer."""
        with LogContext(NODE, f"creating asset invoice for {asset_id[:8]}...", log_level="info"):
            return await self.invoice_manager.create_asset_invoice(
                description, asset_id, asset_amount, expiry, peer_pubkey
            )

    async def pay_asset_invoice(
        self,
        payment_request: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None,
        peer_pubkey: Optional[str] = None
    ) -> Dict[str, Any]:
        """Pay a Taproot Asset invoice."""
        with LogContext(NODE, "paying asset invoice", log_level="info"):
            return await self.payment_manager.pay_asset_invoice(
                payment_request, fee_limit_sats, asset_id, peer_pubkey
            )

    async def update_after_payment(
        self,
        payment_request: str,
        payment_hash: str,
        fee_limit_sats: Optional[int] = None,
        asset_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update Taproot Assets after a payment has been made through the LNbits wallet."""
        with LogContext(NODE, f"updating after payment {payment_hash[:8]}...", log_level="info"):
            return await self.payment_manager.update_after_payment(
                payment_request, payment_hash, fee_limit_sats, asset_id
            )

    async def monitor_invoice(self, payment_hash: str):
        """
        Monitor a specific invoice for state changes.
        
        This method delegates to the transfer_manager's implementation
        which includes direct settlement logic.
        """
        with LogContext(NODE, f"monitoring invoice {payment_hash[:8]}...", log_level="debug"):
            return await self.transfer_manager.monitor_invoice(payment_hash)

    async def close(self):
        """Close the gRPC channels."""
        log_debug(NODE, "Closing gRPC channels")
        await self.channel.close()
        await self.ln_channel.close()
        await self.tap_channel.close()
        log_debug(NODE, "gRPC channels closed")
