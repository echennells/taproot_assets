"""
Asset service for Taproot Assets extension.
Handles asset-related business logic.
"""
from typing import Dict, Any, Optional, List, Tuple, Union
from http import HTTPStatus
from loguru import logger

from lnbits.core.models import WalletTypeInfo, User
from lnbits.core.crud import get_user

from ..models import TaprootAsset, AssetBalance, AssetTransaction
from ..tapd.taproot_factory import TaprootAssetsFactory
from ..error_utils import raise_http_exception, ErrorContext
from ..logging_utils import API, ASSET, log_info, log_warning, log_error
# Import from crud re-exports
from ..crud import (
    get_assets,
    get_asset_balance,
    get_wallet_asset_balances,
    get_asset_transactions
)
from .notification_service import NotificationService
from .transaction_service import TransactionService


class AssetService:
    """
    Service for handling Taproot Assets.
    This service encapsulates asset-related business logic.
    
    This is the primary entry point for application-level asset retrieval.
    It provides methods for retrieving assets with user context (list_assets)
    and without user context (get_raw_assets).
    """
    
    @staticmethod
    async def list_assets(wallet: WalletTypeInfo, auto_sync: bool = True) -> List[Dict[str, Any]]:
        """
        List all Taproot Assets for the current user with balance information.

        This is the primary method that should be used by API endpoints and other
        services when user context is available. It provides assets enriched with
        user balance information and sends appropriate WebSocket notifications.

        Args:
            wallet: The wallet information
            auto_sync: Whether to auto-sync balances with tapd (default True)

        Returns:
            List[Dict[str, Any]]: List of assets with balance information
        """
        with ErrorContext("list_assets", ASSET):
            # Create a wallet instance using the factory
            taproot_wallet = await TaprootAssetsFactory.create_wallet(
                user_id=wallet.wallet.user,
                wallet_id=wallet.wallet.id
            )

            # Get assets from tapd - force refresh to ensure we have latest channel balances
            assets_data = await taproot_wallet.node.asset_manager.list_assets(force_refresh=True)

            # Get user information
            user = await get_user(wallet.wallet.user)
            if not user or not user.wallets:
                return []

            # Auto-sync balances with tapd if enabled
            # This ensures user_balance always matches actual tapd channel balances
            if auto_sync:
                try:
                    await AssetService.sync_balances_with_tapd(wallet)
                except Exception as e:
                    log_warning(ASSET, f"Auto-sync failed (non-fatal): {str(e)}")

            # Get user's wallet asset balances (now synced)
            wallet_balances = {}
            for user_wallet in user.wallets:
                balances = await get_wallet_asset_balances(user_wallet.id)
                for balance in balances:
                    wallet_balances[balance.asset_id] = balance.dict()

            # Enhance the assets data with user balance information
            for asset in assets_data:
                asset_id = asset.get("asset_id")
                if asset_id in wallet_balances:
                    asset["user_balance"] = wallet_balances[asset_id]["balance"]
                else:
                    asset["user_balance"] = 0

            # Send WebSocket notification with assets data using NotificationService
            if assets_data:
                await NotificationService.notify_assets_update(wallet.wallet.user, assets_data)

            return assets_data
    
    @staticmethod
    async def get_raw_assets(force_refresh=False) -> List[Dict[str, Any]]:
        """
        Get raw asset data without user balance information.
        
        This method should be used when:
        1. No user context is available
        2. Only basic asset information is needed
        3. Calling from other services or utilities
        
        Args:
            force_refresh: Whether to force a refresh from the node
            
        Returns:
            List[Dict[str, Any]]: List of raw assets
        """
        with ErrorContext("get_raw_assets", ASSET):
            # Create a minimal wallet instance without user/wallet IDs
            taproot_wallet = await TaprootAssetsFactory.create_wallet()
            
            # Get assets directly from the node manager
            return await taproot_wallet.node.asset_manager.list_assets(force_refresh=force_refresh)
    
    @staticmethod
    async def get_asset_balances(wallet: WalletTypeInfo) -> List[AssetBalance]:
        """
        Get all asset balances for the current wallet.
        
        Args:
            wallet: The wallet information
            
        Returns:
            List[AssetBalance]: List of asset balances
            
        Raises:
            HTTPException: If there's an error retrieving asset balances
        """
        with ErrorContext("get_asset_balances", ASSET):
            balances = await get_wallet_asset_balances(wallet.wallet.id)
            return balances
    
    @staticmethod
    async def get_asset_balance(asset_id: str, wallet: WalletTypeInfo) -> Dict[str, Any]:
        """
        Get the balance for a specific asset in the current wallet.
        
        Args:
            asset_id: The asset ID
            wallet: The wallet information
            
        Returns:
            Dict[str, Any]: Asset balance information
            
        Raises:
            HTTPException: If there's an error retrieving the asset balance
        """
        with ErrorContext("get_asset_balance", ASSET):
            balance = await get_asset_balance(wallet.wallet.id, asset_id)
            if not balance:
                return {"wallet_id": wallet.wallet.id, "asset_id": asset_id, "balance": 0}
            return balance
    
    @staticmethod
    async def get_asset_transactions(
        wallet: WalletTypeInfo,
        asset_id: Optional[str] = None,
        limit: int = 100
    ) -> List[AssetTransaction]:
        """
        Get asset transactions for the current wallet.

        Args:
            wallet: The wallet information
            asset_id: Optional asset ID to filter transactions
            limit: Maximum number of transactions to return

        Returns:
            List[AssetTransaction]: List of asset transactions

        Raises:
            HTTPException: If there's an error retrieving asset transactions
        """
        with ErrorContext("get_asset_transactions", ASSET):
            transactions = await get_asset_transactions(wallet.wallet.id, asset_id, limit)
            return transactions

    @staticmethod
    async def sync_balances_with_tapd(wallet: WalletTypeInfo) -> Dict[str, Any]:
        """
        Sync user asset balances with actual tapd channel balances.

        This method:
        1. Gets actual asset balances from tapd channels
        2. Compares with LNbits internal user_balance
        3. Creates adjustment transactions to reconcile differences

        Args:
            wallet: The wallet information

        Returns:
            Dict with sync results including adjustments made
        """
        with ErrorContext("sync_balances_with_tapd", ASSET):
            results = {
                "synced": [],
                "errors": [],
                "no_change": []
            }

            try:
                # Create wallet instance to access tapd
                taproot_wallet = await TaprootAssetsFactory.create_wallet(
                    user_id=wallet.wallet.user,
                    wallet_id=wallet.wallet.id
                )

                # Get actual channel balances from tapd
                channel_assets = await taproot_wallet.node.asset_manager.list_channel_assets(force_refresh=True)

                # Sum up local_balance per asset_id across all channels
                tapd_balances: Dict[str, int] = {}
                asset_names: Dict[str, str] = {}
                for channel_asset in channel_assets:
                    asset_id = channel_asset.get("asset_id")
                    if not asset_id:
                        continue
                    local_balance = int(channel_asset.get("local_balance", 0))
                    tapd_balances[asset_id] = tapd_balances.get(asset_id, 0) + local_balance
                    # Track asset name for logging
                    if asset_id not in asset_names:
                        asset_names[asset_id] = channel_asset.get("name", "Unknown")

                log_info(ASSET, f"Tapd balances: {tapd_balances}")

                # Get current LNbits balances for this wallet
                current_balances = await get_wallet_asset_balances(wallet.wallet.id)
                lnbits_balances: Dict[str, int] = {}
                for balance in current_balances:
                    lnbits_balances[balance.asset_id] = balance.balance

                log_info(ASSET, f"LNbits balances: {lnbits_balances}")

                # Process each asset that exists in tapd
                for asset_id, tapd_balance in tapd_balances.items():
                    lnbits_balance = lnbits_balances.get(asset_id, 0)
                    difference = tapd_balance - lnbits_balance
                    asset_name = asset_names.get(asset_id, "Unknown")

                    if difference == 0:
                        results["no_change"].append({
                            "asset_id": asset_id,
                            "name": asset_name,
                            "balance": tapd_balance
                        })
                        continue

                    # Create adjustment transaction
                    try:
                        tx_type = "credit" if difference > 0 else "debit"
                        adjustment_amount = abs(difference)

                        success, tx, new_balance = await TransactionService.record_transaction(
                            wallet_id=wallet.wallet.id,
                            asset_id=asset_id,
                            amount=adjustment_amount,
                            tx_type=tx_type,
                            description=f"Balance sync adjustment ({tx_type} {adjustment_amount} to match tapd)",
                            create_tx_record=True
                        )

                        if success:
                            log_info(ASSET, f"Synced {asset_name} ({asset_id}): {lnbits_balance} -> {tapd_balance} (adjustment: {difference:+d})")
                            results["synced"].append({
                                "asset_id": asset_id,
                                "name": asset_name,
                                "old_balance": lnbits_balance,
                                "new_balance": tapd_balance,
                                "adjustment": difference
                            })
                        else:
                            log_error(ASSET, f"Failed to sync {asset_name} ({asset_id})")
                            results["errors"].append({
                                "asset_id": asset_id,
                                "name": asset_name,
                                "error": "Failed to record adjustment transaction"
                            })
                    except Exception as e:
                        log_error(ASSET, f"Error syncing {asset_name} ({asset_id}): {str(e)}")
                        results["errors"].append({
                            "asset_id": asset_id,
                            "name": asset_name,
                            "error": str(e)
                        })

                # Log summary
                log_info(ASSET, f"Sync complete: {len(results['synced'])} synced, {len(results['no_change'])} unchanged, {len(results['errors'])} errors")

                return results

            except Exception as e:
                log_error(ASSET, f"Failed to sync balances: {str(e)}")
                results["errors"].append({"error": str(e)})
                return results
