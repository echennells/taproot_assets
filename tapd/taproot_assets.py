import json
from typing import List, Dict, Any, Optional
from loguru import logger

from lnbits.utils.cache import cache

from .taproot_adapter import (
    taprootassets_pb2,
    lightning_pb2
)
from ..tapd_settings import ASSET_CACHE_EXPIRY_SECONDS

class TaprootAssetManager:
    """
    Handles Taproot Asset management functionality.
    This class is responsible for listing and managing Taproot Assets.
    This is the single source for direct tapd communication regarding assets.
    """
    # Cache keys and expiry times
    ASSET_CACHE_KEY = "taproot:assets:list"
    CHANNEL_ASSET_CACHE_KEY = "taproot:channel_assets:list"
    ASSET_CACHE_EXPIRY = ASSET_CACHE_EXPIRY_SECONDS

    def __init__(self, node):
        """
        Initialize the asset manager with a reference to the node.

        Args:
            node: The TaprootAssetsNodeExtension instance
        """
        self.node = node
        self.node_alias_cache = {}  # Cache for node aliases

    async def get_node_alias(self, pubkey: str) -> str:
        """
        Get the alias/name for a node given its pubkey.
        
        Args:
            pubkey: The node's public key
            
        Returns:
            str: The node's alias/name, or truncated pubkey if not found
        """
        # Check cache first
        if pubkey in self.node_alias_cache:
            return self.node_alias_cache[pubkey]
        
        try:
            # Use Lightning RPC to get node info
            request = lightning_pb2.NodeInfoRequest(
                pub_key=pubkey,
                include_channels=False
            )
            response = await self.node.ln_stub.GetNodeInfo(request)
            
            if response and response.node and response.node.alias:
                alias = response.node.alias
                self.node_alias_cache[pubkey] = alias
                return alias
        except Exception as e:
            logger.debug(f"Could not get node alias for {pubkey[:16]}...: {e}")
        
        # Fallback to truncated pubkey
        fallback = f"{pubkey[:16]}..."
        self.node_alias_cache[pubkey] = fallback
        return fallback

    async def list_assets(self, force_refresh=False) -> List[Dict[str, Any]]:
        """
        List all Taproot Assets with caching.
        
        Args:
            force_refresh: Whether to force a refresh from the node
            
        Returns:
            List[Dict[str, Any]]: List of assets
        """
        logger.info(f"list_assets called with force_refresh={force_refresh}")
        
        # Check cache first if not forcing refresh
        if not force_refresh:
            cached_assets = cache.get(self.ASSET_CACHE_KEY)
            if cached_assets:
                logger.info(f"Returning {len(cached_assets)} cached assets")
                return cached_assets
        
        logger.info("No cache hit, fetching from tapd")
        try:
            # Get all assets from tapd
            logger.info("Creating ListAssetRequest")
            # Use empty request - the parameters were causing issues with v0.15.0
            request = taprootassets_pb2.ListAssetRequest()
            
            logger.info(f"Making RPC call to ListAssets on stub: {self.node.stub}")
            logger.info(f"Node host: {self.node.host}")
            logger.info(f"Request params: with_witness={request.with_witness}, include_spent={request.include_spent}, include_leased={request.include_leased}, include_unconfirmed_mints={request.include_unconfirmed_mints}")
            
            response = await self.node.stub.ListAssets(request, timeout=10)
            logger.info(f"ListAssets RPC completed successfully, got {len(response.assets)} assets")

            # Convert response assets to dictionary format
            assets = []
            for asset in response.assets:
                assets.append({
                    "name": asset.asset_genesis.name.decode('utf-8') if isinstance(asset.asset_genesis.name, bytes) else asset.asset_genesis.name,
                    "asset_id": asset.asset_genesis.asset_id.hex() if isinstance(asset.asset_genesis.asset_id, bytes) else asset.asset_genesis.asset_id,
                    "type": str(asset.asset_genesis.asset_type),
                    "amount": str(asset.amount),
                    "genesis_point": asset.asset_genesis.genesis_point,
                    "meta_hash": asset.asset_genesis.meta_hash.hex() if isinstance(asset.asset_genesis.meta_hash, bytes) else asset.asset_genesis.meta_hash,
                    "version": str(asset.version),
                    "is_spent": asset.is_spent,
                    "script_key": asset.script_key.hex() if isinstance(asset.script_key, bytes) else asset.script_key
                })

            # Get channel assets
            channel_assets = await self.list_channel_assets(force_refresh=force_refresh)

            # Create asset map for lookup
            asset_map = {asset["asset_id"]: asset for asset in assets}
            
            # Group channel assets by asset_id
            channel_assets_by_id = {}
            for channel_asset in channel_assets:
                asset_id = channel_asset["asset_id"]
                if asset_id not in channel_assets_by_id:
                    channel_assets_by_id[asset_id] = []
                channel_assets_by_id[asset_id].append(channel_asset)

            # Process assets with channels
            result_assets = []
            
            # Add assets with channels
            for asset_id, channels in channel_assets_by_id.items():
                base_asset = asset_map.get(asset_id, {
                    "asset_id": asset_id,
                    "name": channels[0].get("name", "") or "Unknown Asset",
                    "type": "CHANNEL_ONLY",
                    "amount": "0",
                })
                
                # Add each channel as a separate asset entry
                for channel in channels:
                    asset_with_channel = base_asset.copy()
                    
                    # Get node alias for the peer
                    peer_pubkey = channel["remote_pubkey"]
                    peer_alias = await self.get_node_alias(peer_pubkey)
                    
                    asset_with_channel["channel_info"] = {
                        "channel_point": channel["channel_point"],
                        "capacity": channel["capacity"],
                        "local_balance": channel["local_balance"],
                        "remote_balance": channel["remote_balance"],
                        "peer_pubkey": peer_pubkey,
                        "peer_alias": peer_alias,  # Add human-readable node name
                        "channel_id": channel["channel_id"],
                        "active": channel.get("active", True)  # Add active status
                    }
                    asset_with_channel["amount"] = str(channel["local_balance"])
                    result_assets.append(asset_with_channel)
            
            # We're not adding non-channel assets anymore, per the requirements
            # The commented code below would add regular assets without channels
            # which we now want to filter out
            
            # # Add remaining assets without channels
            # for asset_id, asset in asset_map.items():
            #     if asset_id not in channel_assets_by_id:
            #         result_assets.append(asset)

            # Store in cache before returning
            cache.set(self.ASSET_CACHE_KEY, result_assets, expiry=self.ASSET_CACHE_EXPIRY)
            return result_assets
        except Exception as e:
            logger.error(f"Failed to list assets: {str(e)}")
            logger.error(f"Exception type: {type(e)}")
            logger.error(f"Exception details: {repr(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []  # Return empty list on error

    async def list_channel_assets(self, force_refresh=False) -> List[Dict[str, Any]]:
        """
        List all Lightning channels with Taproot Assets.

        Args:
            force_refresh: Whether to force a refresh from the node
            
        Returns:
            A list of dictionaries containing channel and asset information.
        """
        # Check cache first if not forcing refresh
        if not force_refresh:
            cached_assets = cache.get(self.CHANNEL_ASSET_CACHE_KEY)
            if cached_assets:
                return cached_assets
        try:
            # Get channels from LND
            request = lightning_pb2.ListChannelsRequest()
            response = await self.node.ln_stub.ListChannels(request, timeout=10)

            channel_assets = []

            # Process each channel
            for channel in response.channels:
                # Skip channels without custom_channel_data
                if not hasattr(channel, 'custom_channel_data') or not channel.custom_channel_data:
                    continue
                    
                try:
                    # Parse JSON data
                    asset_data = json.loads(channel.custom_channel_data.decode('utf-8'))
                    
                    # Handle new v0.15.0 format with funding_assets
                    if "funding_assets" in asset_data:
                        # Process funding assets (contains full asset details)
                        for asset in asset_data.get("funding_assets", []):
                            asset_genesis = asset.get("asset_genesis", {})
                            asset_id = asset_genesis.get("asset_id", "")
                            name = asset_genesis.get("name", "")
                            
                            if not asset_id:
                                continue
                            
                            # Get balance info from local_assets
                            local_balance = 0
                            for local_asset in asset_data.get("local_assets", []):
                                if local_asset.get("asset_id") == asset_id:
                                    local_balance = local_asset.get("amount", 0)
                                    break
                            
                            # Get remote balance
                            remote_balance = 0
                            for remote_asset in asset_data.get("remote_assets", []):
                                if remote_asset.get("asset_id") == asset_id:
                                    remote_balance = remote_asset.get("amount", 0)
                                    break
                            
                            asset_info = {
                                "asset_id": asset_id,
                                "name": name,
                                "channel_id": str(channel.chan_id),
                                "channel_point": channel.channel_point,
                                "remote_pubkey": channel.remote_pubkey,
                                "capacity": asset_data.get("capacity", 0),
                                "local_balance": local_balance,
                                "remote_balance": remote_balance,
                                "commitment_type": str(channel.commitment_type),
                                "active": channel.active
                            }
                            channel_assets.append(asset_info)
                    
                    # Also handle old format for backwards compatibility
                    elif "assets" in asset_data:
                        for asset in asset_data.get("assets", []):
                            asset_utxo = asset.get("asset_utxo", {})
                            
                            # Extract asset ID
                            asset_id = ""
                            if "asset_id" in asset_utxo:
                                asset_id = asset_utxo["asset_id"]
                            elif "asset_genesis" in asset_utxo and "asset_id" in asset_utxo["asset_genesis"]:
                                asset_id = asset_utxo["asset_genesis"]["asset_id"]
                            
                            # Skip entries without asset ID
                            if not asset_id:
                                continue
                                
                            # Extract name
                            name = ""
                            if "name" in asset_utxo:
                                name = asset_utxo["name"]
                            elif "asset_genesis" in asset_utxo and "name" in asset_utxo["asset_genesis"]:
                                name = asset_utxo["asset_genesis"]["name"]
                            
                            # Create asset info dictionary
                            asset_info = {
                                "asset_id": asset_id,
                                "name": name,
                                "channel_id": str(channel.chan_id),
                                "channel_point": channel.channel_point,
                                "remote_pubkey": channel.remote_pubkey,
                                "capacity": asset.get("capacity", 0),
                                "local_balance": asset.get("local_balance", 0),
                                "remote_balance": asset.get("remote_balance", 0),
                                "commitment_type": str(channel.commitment_type),
                                "active": channel.active  # Include active status from channel
                            }
                            
                            channel_assets.append(asset_info)
                except Exception as e:
                    logger.debug(f"Failed to process channel {channel.channel_point}: {e}")
                    continue
                    
            # Store in cache before returning
            cache.set(self.CHANNEL_ASSET_CACHE_KEY, channel_assets, expiry=self.ASSET_CACHE_EXPIRY)
            return channel_assets
        except Exception as e:
            logger.debug(f"Error listing channel assets: {e}")
            return []
