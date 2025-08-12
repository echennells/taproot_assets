#!/usr/bin/env python3
"""
Test script for LNURL payment flow with Taproot Assets.

This script demonstrates:
1. How to decode an LNURL from bitcoinswitch
2. How to check if it supports taproot assets
3. How to pay it using taproot assets

Usage:
    python test_lnurl_flow.py <lnurl> <amount_sats> [asset_id]
"""
import asyncio
import sys
from typing import Optional

try:
    from lnurl import url_decode as lnurl_decode
except ImportError:
    # Fallback for newer versions of lnurl package
    from lnurl import decode as lnurl_decode
import httpx


async def test_lnurl_flow(lnurl_string: str, amount_sats: int, asset_id: Optional[str] = None):
    """Test the LNURL payment flow."""
    print(f"Testing LNURL: {lnurl_string}")
    print(f"Amount: {amount_sats} sats")
    if asset_id:
        print(f"Asset ID: {asset_id}")
    
    # Step 1: Decode LNURL
    try:
        url = str(lnurl_decode(lnurl_string))
        print(f"\nDecoded URL: {url}")
    except Exception as e:
        print(f"Error decoding LNURL: {e}")
        return
    
    # Step 2: Fetch LNURL parameters
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10)
            data = response.json()
            print(f"\nLNURL Response:")
            print(f"- Tag: {data.get('tag')}")
            print(f"- Min: {data.get('minSendable', 0) // 1000} sats")
            print(f"- Max: {data.get('maxSendable', 0) // 1000} sats")
            print(f"- Callback: {data.get('callback')}")
            print(f"- Comment allowed: {data.get('commentAllowed', 0)}")
            
            # Check for asset support
            if data.get('acceptsAssets'):
                print(f"\n✅ This LNURL accepts Taproot Assets!")
                print(f"Accepted assets: {data.get('acceptedAssetIds', [])}")
                if data.get('assetMetadata'):
                    print(f"Asset metadata: {data.get('assetMetadata')}")
            else:
                print(f"\n❌ This LNURL does not accept Taproot Assets")
            
            # Step 3: Make callback to get invoice
            callback_url = data.get('callback')
            if not callback_url:
                print("Error: No callback URL found")
                return
            
            amount_msat = amount_sats * 1000
            callback_params = {'amount': amount_msat}
            
            # Add asset_id if supported and provided
            if asset_id and data.get('acceptsAssets') and asset_id in data.get('acceptedAssetIds', []):
                callback_params['asset_id'] = asset_id
                print(f"\nMaking callback with asset_id: {asset_id}")
            else:
                print(f"\nMaking regular Lightning callback")
            
            cb_response = await client.get(callback_url, params=callback_params, timeout=10)
            cb_data = cb_response.json()
            
            if cb_data.get('status') == 'ERROR':
                print(f"Error from callback: {cb_data.get('reason')}")
                return
            
            pr = cb_data.get('pr')
            if pr:
                print(f"\n✅ Received payment request!")
                print(f"Invoice: {pr[:50]}...")
                if cb_data.get('successAction'):
                    print(f"Success action: {cb_data.get('successAction')}")
            else:
                print("Error: No payment request received")
            
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_lnurl_flow.py <lnurl> <amount_sats> [asset_id]")
        sys.exit(1)
    
    lnurl = sys.argv[1]
    amount = int(sys.argv[2])
    asset_id = sys.argv[3] if len(sys.argv) > 3 else None
    
    asyncio.run(test_lnurl_flow(lnurl, amount, asset_id))