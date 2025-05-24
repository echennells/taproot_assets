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

    async def list_assets(self, force_refresh=False) -> List[Dict[str, Any]]:
        """
        List all Taproot Assets with caching.
        
        Args:
            force_refresh: Whether to force a refresh from the node
            
        Returns:
            List[Dict[str, Any]]: List of assets
        """
        # Check cache first if not forcing refresh
        if not force_refresh:
            cached_assets = cache.get(self.ASSET_CACHE_KEY)
            if cached_assets:
                return cached_assets
        try:
            # Get all assets from tapd
            request = taprootassets_pb2.ListAssetRequest(
                with_witness=False,
                include_spent=False,
                include_leased=True,
                include_unconfirmed_mints=True
            )
            response = await self.node.stub.ListAssets(request, timeout=10)

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
                    asset_with_channel["channel_info"] = {
                        "channel_point": channel["channel_point"],
                        "capacity": channel["capacity"],
                        "local_balance": channel["local_balance"],
                        "remote_balance": channel["remote_balance"],
                        "peer_pubkey": channel["remote_pubkey"],
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
                    
                    # Handle newer litd/tapd format with local_assets and funding_assets
                    local_assets = asset_data.get("local_assets", [])
                    funding_assets = asset_data.get("funding_assets", [])
                    
                    # Get channel-level capacity and balance info
                    channel_capacity = asset_data.get("capacity", 0)
                    channel_local_balance = asset_data.get("local_balance", 0)
                    channel_remote_balance = asset_data.get("remote_balance", 0)
                    
                    # Process local assets (newer format)
                    for local_asset in local_assets:
                        asset_id = local_asset.get("asset_id", "")
                        if not asset_id:
                            continue
                            
                        # Find corresponding funding asset for name and other details
                        funding_asset = None
                        for fa in funding_assets:
                            if fa.get("asset_genesis", {}).get("asset_id") == asset_id:
                                funding_asset = fa
                                break
                        
                        # Extract name from funding asset
                        name = ""
                        if funding_asset:
                            name = funding_asset.get("asset_genesis", {}).get("name", "")
                        
                        # Create asset info dictionary
                        asset_info = {
                            "asset_id": asset_id,
                            "name": name,
                            "channel_id": str(channel.chan_id),
                            "channel_point": channel.channel_point,
                            "remote_pubkey": channel.remote_pubkey,
                            "capacity": channel_capacity,
                            "local_balance": local_asset.get("amount", 0),
                            "remote_balance": channel_remote_balance,
                            "commitment_type": str(channel.commitment_type),
                            "active": channel.active
                        }
                        
                        channel_assets.append(asset_info)
                    
                    # Fallback: Process legacy "assets" format if no local_assets found
                    if not local_assets:
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
                                "active": channel.active
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
