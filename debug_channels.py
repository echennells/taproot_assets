#!/usr/bin/env python3

import asyncio
import json
import sys
import os

# Add the LNBits root directory to Python path
sys.path.insert(0, '/app')

from lnbits.extensions.taproot_assets.tapd.taproot_factory import TaprootAssetsFactory
from lnbits.extensions.taproot_assets.logging_utils import log_info, log_error, log_debug

async def debug_channels():
    """Debug channel detection issues"""
    
    print("=== Taproot Assets Channel Debug ===")
    
    try:
        # Create a wallet instance
        taproot_wallet = await TaprootAssetsFactory.create_wallet()
        
        print("\n1. Testing direct LND ListChannels call...")
        
        # Get channels from LND directly
        from lnbits.extensions.taproot_assets.tapd.taproot_adapter import lightning_pb2
        request = lightning_pb2.ListChannelsRequest()
        response = await taproot_wallet.node.ln_stub.ListChannels(request, timeout=10)
        
        print(f"Found {len(response.channels)} total channels")
        
        for i, channel in enumerate(response.channels):
            print(f"\nChannel {i+1}:")
            print(f"  Channel ID: {channel.chan_id}")
            print(f"  Channel Point: {channel.channel_point}")
            print(f"  Remote Pubkey: {channel.remote_pubkey}")
            print(f"  Active: {channel.active}")
            print(f"  Capacity: {channel.capacity}")
            print(f"  Local Balance: {channel.local_balance}")
            print(f"  Remote Balance: {channel.remote_balance}")
            print(f"  Has custom_channel_data: {hasattr(channel, 'custom_channel_data') and bool(channel.custom_channel_data)}")
            
            if hasattr(channel, 'custom_channel_data') and channel.custom_channel_data:
                try:
                    custom_data = json.loads(channel.custom_channel_data.decode('utf-8'))
                    print(f"  Custom channel data: {json.dumps(custom_data, indent=4)}")
                except Exception as e:
                    print(f"  Error parsing custom_channel_data: {e}")
                    print(f"  Raw custom_channel_data: {channel.custom_channel_data}")
            else:
                print("  No custom_channel_data found")
        
        print("\n2. Testing asset manager list_channel_assets...")
        
        # Test the asset manager method
        channel_assets = await taproot_wallet.node.asset_manager.list_channel_assets(force_refresh=True)
        
        print(f"Asset manager found {len(channel_assets)} channel assets:")
        for asset in channel_assets:
            print(f"  Asset: {json.dumps(asset, indent=2)}")
        
        print("\n3. Testing asset manager list_assets...")
        
        # Test the full list_assets method
        all_assets = await taproot_wallet.node.asset_manager.list_assets(force_refresh=True)
        
        print(f"Asset manager found {len(all_assets)} total assets:")
        for asset in all_assets:
            print(f"  Asset: {json.dumps(asset, indent=2)}")
        
        print("\n4. Testing raw ListAssets call...")
        
        # Test raw ListAssets call
        from lnbits.extensions.taproot_assets.tapd.taproot_adapter import taprootassets_pb2
        request = taprootassets_pb2.ListAssetRequest(
            with_witness=False,
            include_spent=False,
            include_leased=True,
            include_unconfirmed_mints=True
        )
        response = await taproot_wallet.node.stub.ListAssets(request, timeout=10)
        
        print(f"Raw ListAssets found {len(response.assets)} assets:")
        for asset in response.assets:
            print(f"  Asset ID: {asset.asset_genesis.asset_id.hex()}")
            print(f"  Name: {asset.asset_genesis.name.decode('utf-8') if isinstance(asset.asset_genesis.name, bytes) else asset.asset_genesis.name}")
            print(f"  Amount: {asset.amount}")
            print(f"  Is Spent: {asset.is_spent}")
        
    except Exception as e:
        log_error("DEBUG", f"Error during channel debug: {str(e)}")
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Clean up
        if 'taproot_wallet' in locals():
            await taproot_wallet.node.close()

if __name__ == "__main__":
    asyncio.run(debug_channels())
