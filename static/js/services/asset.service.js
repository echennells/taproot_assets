/**
 * Asset Service for Taproot Assets extension
 * Updated to use consolidated DataUtils
 */

const AssetService = {
  /**
   * Get all assets with information about channels and balances
   * @param {Object} wallet - Wallet object with adminkey
   * @returns {Promise<Array>} - Promise that resolves with assets
   */
  async getAssets(wallet) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      console.log('Fetching assets for wallet', wallet.id);
      
      // Request assets from the API
      const response = await LNbits.api.request(
        'GET', 
        '/taproot_assets/api/v1/taproot/listassets', 
        wallet.adminkey
      );
      
      if (!response || !response.data) {
        console.warn('No assets returned from API');
        return [];
      }
      
      // Process the assets
      const assets = Array.isArray(response.data) ? [...response.data] : [];
      
      // Get balances for assets
      if (assets.length > 0) {
        try {
          // Get all balances at once
          const balancesResponse = await LNbits.api.request(
            'GET', 
            '/taproot_assets/api/v1/taproot/asset-balances', 
            wallet.adminkey
          );
          
          if (balancesResponse && balancesResponse.data) {
            // Create a map of asset ID to balance
            const balanceMap = {};
            balancesResponse.data.forEach(balance => {
              if (balance.asset_id) {
                balanceMap[balance.asset_id] = balance.balance || 0;
              }
            });
            
            // Add balance information to assets
            assets.forEach(asset => {
              if (asset.asset_id && balanceMap[asset.asset_id] !== undefined) {
                asset.user_balance = balanceMap[asset.asset_id];
              } else {
                asset.user_balance = 0;
              }
            });
          }
        } catch (balanceError) {
          console.error('Error fetching asset balances:', balanceError);
          // Continue with assets even if balances fail
        }
      }
      
      // Update the store
      window.taprootStore.actions.setAssets(assets);
      
      // Create a global asset map for quick lookups
      this._updateAssetMap(assets);
      
      return assets;
    } catch (error) {
      console.error('Failed to fetch assets:', error);
      return []; 
    } finally {
      // Set loading state to false in store
      window.taprootStore.actions.setAssetsLoading(false);
    }
  },
  
  /**
   * Update the global asset map for quick lookups
   * @param {Array} assets - Assets to add to the map
   * @private
   */
  _updateAssetMap(assets) {
    // Create a global map if it doesn't exist
    if (!window.assetMap) {
      window.assetMap = {};
    }
    
    // Update the map with new asset data
    assets.forEach(asset => {
      if (asset.asset_id) {
        window.assetMap[asset.asset_id] = {
          name: asset.name || 'Unknown',
          type: asset.type || 'unknown',
          meta_hash: asset.meta_hash,
          // Add any other properties that might be needed for lookups
        };
      }
    });
  },
  
  /**
   * Get a specific asset by ID
   * @param {string} assetId - ID of the asset to get
   * @returns {Object|null} - Asset object or null if not found
   */
  getAssetById(assetId) {
    if (!assetId) return null;
    
    // First try the store
    const storeAsset = window.taprootStore?.state?.assets?.find(asset => asset.asset_id === assetId);
    if (storeAsset) return storeAsset;
    
    // If not in store, check the map
    if (window.assetMap && window.assetMap[assetId]) {
      // Return a minimal asset object from the map
      return {
        asset_id: assetId,
        name: window.assetMap[assetId].name,
        type: window.assetMap[assetId].type,
        meta_hash: window.assetMap[assetId].meta_hash
      };
    }
    
    return null;
  },
  
  /**
   * Get the name of an asset by ID
   * @param {string} assetId - ID of the asset to get name for
   * @returns {string} - Asset name or "Unknown" if not found
   */
  getAssetName(assetId) {
    // Try to get from global map first (fastest)
    if (window.assetMap && window.assetMap[assetId]) {
      return window.assetMap[assetId].name || 'Unknown';
    }
    
    // Then try the store
    const asset = this.getAssetById(assetId);
    return asset ? asset.name || 'Unknown' : 'Unknown';
  },

  /**
   * Check if a user can send this asset (has balance and active channel)
   * @param {Object} asset - Asset to check
   * @returns {boolean} - Whether user can send this asset
   */
  canSendAsset(asset) {
    if (!asset) return false;
    
    // First check if asset is active
    if (asset.channel_info && asset.channel_info.active === false) {
      return false;
    }
    
    // Then check if user has balance
    const userBalance = asset.user_balance || 0;
    return userBalance > 0;
  },
  
  /**
   * Get the maximum receivable amount for an asset
   * @param {Object} asset - Asset to get max receivable for
   * @returns {number} - Maximum receivable amount
   */
  getMaxReceivableAmount(asset) {
    if (!asset || !asset.channel_info) return 0;

    const channelInfo = asset.channel_info;
    // The max receivable is simply the remote balance (what the peer has that they can send to us)
    if (channelInfo.remote_balance !== undefined) {
      return parseFloat(channelInfo.remote_balance);
    }

    return 0;
  },
  
  /**
   * Format asset balance using DataUtils
   * @param {number|string} balance - Balance to format 
   * @param {number} decimals - Number of decimal places
   * @returns {string} - Formatted balance
   */
  formatBalance(balance, decimals = 0) {
    return DataUtils.formatAssetBalance(balance, decimals);
  },
  
  /**
   * Parse asset value using DataUtils
   * @param {number|string} value - Value to parse
   * @returns {number} - Parsed numeric value
   */
  parseValue(value) {
    return DataUtils.parseAssetValue(value);
  },
  
  /**
   * Process asset data from WebSocket updates
   * @param {Object} data - WebSocket data with asset information
   */
  processWebSocketUpdate(data) {
    if (data?.type === 'assets_update' && Array.isArray(data.data)) {
      // Update the asset map for quick lookups
      this._updateAssetMap(data.data);
      
      // Update the store if needed
      if (window.taprootStore?.state?.assets) {
        // Merge with existing assets
        const existingAssets = [...window.taprootStore.state.assets];
        const assetIds = new Set(existingAssets.map(a => a.asset_id));
        
        // Update existing and add new
        const updatedAssets = [...existingAssets];
        data.data.forEach(asset => {
          if (asset.asset_id) {
            if (assetIds.has(asset.asset_id)) {
              // Update existing
              const index = updatedAssets.findIndex(a => a.asset_id === asset.asset_id);
              if (index !== -1) {
                updatedAssets[index] = {...updatedAssets[index], ...asset};
              }
            } else {
              // Add new
              updatedAssets.push(asset);
              assetIds.add(asset.asset_id);
            }
          }
        });
        
        // Update the store
        window.taprootStore.actions.setAssets(updatedAssets);
      }
    }
  }
};

// Export the service
window.AssetService = AssetService;
