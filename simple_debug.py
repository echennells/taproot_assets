#!/usr/bin/env python3

import asyncio
import json
import sys
import os
import grpc
import grpc.aio

# Add the LNBits root directory to Python path
sys.path.insert(0, '/app')

async def debug_channels():
    """Simple debug script to check channels"""
    
    print("=== Simple Taproot Assets Channel Debug ===")
    
    try:
        # Import settings
        from lnbits.extensions.taproot_assets.tapd_settings import taproot_settings
        
        print(f"Host: {taproot_settings.tapd_host}")
        print(f"Network: {taproot_settings.tapd_network}")
        
        # Read TLS certificate
        with open(taproot_settings.tapd_tls_cert_path, 'rb') as f:
            cert = f.read()
        
        # Read Lightning macaroon
        with open(taproot_settings.lnd_macaroon_path, 'rb') as f:
            ln_macaroon = f.read().hex()
        
        # Setup gRPC credentials for Lightning
        credentials = grpc.ssl_channel_credentials(cert)
        ln_auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", ln_macaroon)], None)
        )
        ln_combined_creds = grpc.composite_channel_credentials(credentials, ln_auth_creds)
        
        # Create Lightning gRPC channel
        ln_channel = grpc.aio.secure_channel(taproot_settings.tapd_host, ln_combined_creds)
        
        # Import protobuf files directly
        import importlib.util
        
        # Load lightning_pb2 from the grpc files
        spec = importlib.util.spec_from_file_location(
            "lightning_pb2", 
            "/app/lnbits/extensions/taproot_assets/tapd/lightning_pb2.py"
        )
        lightning_pb2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lightning_pb2)
        
        # Load lightning_pb2_grpc
        spec = importlib.util.spec_from_file_location(
            "lightning_pb2_grpc", 
            "/app/lnbits/extensions/taproot_assets/tapd/lightning_pb2_grpc.py"
        )
        lightning_pb2_grpc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lightning_pb2_grpc)
        
        # Create Lightning client
        ln_stub = lightning_pb2_grpc.LightningStub(ln_channel)
        
        print("\n1. Testing direct LND ListChannels call...")
        
        # Get channels from LND directly
        request = lightning_pb2.ListChannelsRequest()
        response = await ln_stub.ListChannels(request, timeout=10)
        
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
        
        # Now test tapd connection
        print("\n2. Testing tapd connection...")
        
        # Read Taproot macaroon
        with open(taproot_settings.tapd_macaroon_path, 'rb') as f:
            tapd_macaroon = f.read().hex()
        
        # Setup gRPC credentials for Taproot
        tapd_auth_creds = grpc.metadata_call_credentials(
            lambda context, callback: callback([("macaroon", tapd_macaroon)], None)
        )
        tapd_combined_creds = grpc.composite_channel_credentials(credentials, tapd_auth_creds)
        
        # Create Taproot gRPC channel
        tapd_channel = grpc.aio.secure_channel(taproot_settings.tapd_host, tapd_combined_creds)
        
        # Load taprootassets_pb2
        spec = importlib.util.spec_from_file_location(
            "taprootassets_pb2", 
            "/app/lnbits/extensions/taproot_assets/tapd/taprootassets_pb2.py"
        )
        taprootassets_pb2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(taprootassets_pb2)
        
        # Load taprootassets_pb2_grpc
        spec = importlib.util.spec_from_file_location(
            "taprootassets_pb2_grpc", 
            "/app/lnbits/extensions/taproot_assets/tapd/taprootassets_pb2_grpc.py"
        )
        taprootassets_pb2_grpc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(taprootassets_pb2_grpc)
        
        # Create Taproot client
        tapd_stub = taprootassets_pb2_grpc.TaprootAssetsStub(tapd_channel)
        
        # Test raw ListAssets call
        request = taprootassets_pb2.ListAssetRequest(
            with_witness=False,
            include_spent=False,
            include_leased=True,
            include_unconfirmed_mints=True
        )
        response = await tapd_stub.ListAssets(request, timeout=10)
        
        print(f"Raw ListAssets found {len(response.assets)} assets:")
        for asset in response.assets:
            print(f"  Asset ID: {asset.asset_genesis.asset_id.hex()}")
            print(f"  Name: {asset.asset_genesis.name.decode('utf-8') if isinstance(asset.asset_genesis.name, bytes) else asset.asset_genesis.name}")
            print(f"  Amount: {asset.amount}")
            print(f"  Is Spent: {asset.is_spent}")
        
        # Close channels
        await ln_channel.close()
        await tapd_channel.close()
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_channels())
