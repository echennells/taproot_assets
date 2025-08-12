/**
 * Payments Service for Taproot Assets extension
 * Updated to use consolidated DataUtils
 */

const PaymentService = {
  /**
   * Get all payments for the current user
   * @param {Object} wallet - Wallet object with adminkey
   * @param {boolean} cache - Whether to use cache-busting timestamp 
   * @returns {Promise<Array>} - Promise that resolves with payments
   */
  async getPayments(wallet, cache = true) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      // Set loading state in store
      window.taprootStore.actions.setTransactionsLoading(true);
      window.taprootStore.actions.setCurrentWallet(wallet);
      
      // Request payments from the API
      const response = await ApiService.getPayments(wallet.adminkey, cache);
      
      if (!response?.data) {
        window.taprootStore.actions.setPayments([]);
        return [];
      }
      
      // Process the payments using DataUtils
      const payments = Array.isArray(response.data)
        ? response.data.map(payment => this._mapPayment(payment))
        : [];
      
      // Make sure asset names are available
      this._ensureAssetNames(payments);
      
      // Update the store
      window.taprootStore.actions.setPayments(payments);
      
      return payments;
    } catch (error) {
      console.error('Failed to fetch payments:', error);
      window.taprootStore.actions.setPayments([]);
      return [];
    } finally {
      // Ensure loading state is reset
      window.taprootStore.actions.setTransactionsLoading(false);
    }
  },
  
  /**
   * Ensure asset names are available for all payments
   * @param {Array} payments - Array of payment objects
   * @private
   */
  _ensureAssetNames(payments) {
    if (!Array.isArray(payments)) return;
    
    // Create a set of unique asset IDs
    const assetIds = new Set();
    payments.forEach(payment => {
      if (payment.asset_id) {
        assetIds.add(payment.asset_id);
      }
    });
    
    // Make sure all assets are in the global map
    assetIds.forEach(assetId => {
      if (!window.assetMap) window.assetMap = {};
      
      // If asset is not in map, add a placeholder
      if (!window.assetMap[assetId]) {
        // Try to get name from store first
        const asset = window.taprootStore?.state?.assets?.find(a => a.asset_id === assetId);
        if (asset) {
          window.assetMap[assetId] = {
            name: asset.name || 'Unknown',
            type: asset.type || 'unknown'
          };
        } else {
          // Add placeholder
          window.assetMap[assetId] = {
            name: `Asset ${assetId.substring(0, 8)}...`,
            type: 'unknown'
          };
        }
      }
    });
  },
  
  /**
   * Parse an invoice to get payment details
   * @param {Object} wallet - Wallet object with adminkey
   * @param {string} paymentRequest - Payment request to parse
   * @returns {Promise<Object>} - Promise with parsed invoice
   */
  async parseInvoice(wallet, paymentRequest) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      if (!paymentRequest || paymentRequest.trim() === '') {
        throw new Error('Payment request is required');
      }
      
      // Request parsing from the API
      const response = await ApiService.parseInvoice(wallet.adminkey, paymentRequest);
      
      if (!response?.data) {
        throw new Error('Failed to parse invoice: No data returned');
      }
      
      return response.data;
    } catch (error) {
      console.error('Failed to parse invoice:', error);
      throw error;
    }
  },
  
  /**
   * Pay a Taproot Asset invoice
   * @param {Object} wallet - Wallet object with adminkey
   * @param {Object} assetData - Asset data for payment
   * @param {Object} paymentData - Payment data (request, fee limit, etc)
   * @returns {Promise<Object>} - Promise with payment result
   */
  async payInvoice(wallet, assetData, paymentData) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      if (!paymentData?.paymentRequest) {
        throw new Error('Payment request is required');
      }
      
      // Create payload
      const payload = {
        payment_request: paymentData.paymentRequest,
        fee_limit_sats: paymentData.feeLimit || 1000,
        asset_id: assetData.asset_id  // Explicitly send the selected asset ID
      };
      
      // Don't send peer_pubkey - let the backend auto-select based on invoice destination
      
      // Make the payment request
      const response = await ApiService.payInvoice(wallet.adminkey, payload);
      
      if (!response?.data) {
        throw new Error('Failed to process payment: No data returned');
      }
      
      // Check if the payment was successful
      if (!response.data.status || response.data.status === 'failed') {
        // If status is explicitly failed, throw an error with the details
        const errorMessage = response.data.error || 'Payment failed';
        throw new Error(errorMessage);
      }
      
      // Only update UI if payment was successful
      if (response.data.status === 'success') {
        // Update asset information in the store with new balance
        if (response.data.asset_id && assetData && window.taprootStore) {
          // Deduct the asset amount from the user's balance
          const newBalance = (assetData.user_balance || 0) - response.data.asset_amount;
          
          // Update the asset in the store
          window.taprootStore.actions.updateAsset(assetData.asset_id, { 
            user_balance: Math.max(0, newBalance) 
          });
          
          // Make sure this asset is in the global map
          if (!window.assetMap) window.assetMap = {};
          if (!window.assetMap[assetData.asset_id]) {
            window.assetMap[assetData.asset_id] = {
              name: assetData.name || 'Unknown',
              type: assetData.type || 'unknown'
            };
          }
        }
        
        // Create payment record for store
        const payment = {
          id: response.data.payment_hash || Date.now().toString(),
          payment_hash: response.data.payment_hash,
          payment_request: paymentData.paymentRequest,
          asset_id: response.data.asset_id || assetData.asset_id,
          asset_amount: response.data.asset_amount,
          fee_sats: response.data.fee_msat ? Math.ceil(response.data.fee_msat / 1000) : 0,
          memo: response.data.description || '', // Use description from backend response
          status: 'completed',
          user_id: wallet.user,
          wallet_id: wallet.id,
          created_at: new Date().toISOString(),
          preimage: response.data.preimage
        };
        
        // Add mapped payment to store
        const mappedPayment = this._mapPayment(payment);
        window.taprootStore.actions.addPayment(mappedPayment);
      }
      
      return response.data;
    } catch (error) {
      // Check for special cases that might need handling
      if (error.response?.data?.detail && 
          (error.response.data.detail.includes('internal payment') || 
           error.response.data.detail.includes('own invoice'))) {
        // This is likely an internal payment that should be routed differently
        throw {
          ...error,
          isInternalPayment: true,
          message: 'This invoice belongs to another user on this node. System will process it as an internal payment.'
        };
      }
      
      console.error('Failed to pay invoice:', error);
      throw error;
    }
  },
  
  /**
   * Process an internal payment (between users on the same node)
   * @param {Object} wallet - Wallet object with adminkey
   * @param {Object} paymentData - Payment data
   * @returns {Promise<Object>} - Promise with payment result
   */
  async processInternalPayment(wallet, paymentData) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      if (!paymentData?.paymentRequest) {
        throw new Error('Payment request is required');
      }
      
      // Create payload
      const payload = {
        payment_request: paymentData.paymentRequest,
        fee_limit_sats: paymentData.feeLimit || 10,
        asset_id: paymentData.assetId  // Include the selected asset ID
      };
      
      // Use the standard pay endpoint for internal payments
      const response = await ApiService.payInvoice(wallet.adminkey, payload);
      
      if (!response?.data) {
        throw new Error('Failed to process internal payment: No data returned');
      }
      
      // Find the asset in the store
      let asset = null;
      if (window.taprootStore?.state?.assets) {
        asset = window.taprootStore.state.assets.find(a => a.asset_id === response.data.asset_id);
      }
      
      // Update asset information in the store if found
      if (response.data.asset_id && asset) {
        // Deduct the asset amount from the user's balance
        const newBalance = (asset.user_balance || 0) - response.data.asset_amount;
        
        // Update the asset in the store
        window.taprootStore.actions.updateAsset(asset.asset_id, { 
          user_balance: Math.max(0, newBalance) 
        });
        
        // Make sure this asset is in the global map
        if (!window.assetMap) window.assetMap = {};
        if (!window.assetMap[asset.asset_id]) {
          window.assetMap[asset.asset_id] = {
            name: asset.name || 'Unknown',
            type: asset.type || 'unknown'
          };
        }
      }
      
      // Create payment record for store
      const payment = {
        id: response.data.payment_hash || Date.now().toString(),
        payment_hash: response.data.payment_hash,
        payment_request: paymentData.paymentRequest,
        asset_id: response.data.asset_id,
        asset_amount: response.data.asset_amount,
        fee_sats: 0, // Internal payments have zero fee
        memo: response.data.description || '', // Use description from backend response
        status: 'completed',
        user_id: wallet.user,
        wallet_id: wallet.id,
        created_at: new Date().toISOString(),
        preimage: response.data.preimage,
        internal_payment: true
      };
      
      // Add mapped payment to store using DataUtils
      const mappedPayment = this._mapPayment(payment);
      window.taprootStore.actions.addPayment(mappedPayment);
      
      return response.data;
    } catch (error) {
      console.error('Failed to process internal payment:', error);
      throw error;
    }
  },
  
  /**
   * Process and transform a payment object using DataUtils
   * @param {Object} payment - Raw payment data
   * @returns {Object} - Processed payment
   * @private
   */
  _mapPayment(payment) {
    if (!payment) return null;
    
    // Use DataUtils for mapping the transaction
    const mapped = DataUtils.mapTransaction(payment, 'payment');
    
    // Get asset name if not in memo
    if (mapped.asset_id && !mapped.asset_name) {
      mapped.asset_name = this._getAssetName(mapped.asset_id);
      
      // Don't override memo if it already exists
      if (!mapped.memo && mapped.asset_name && mapped.asset_name !== 'Unknown') {
        mapped.memo = '';
      }
    }
    
    // Add additional payment-specific data to extra
    mapped.extra = mapped.extra || {};
    
    mapped.extra.asset_name = mapped.asset_name || this._getAssetName(mapped.asset_id);
    
    return mapped;
  },
  
  /**
   * Get asset name from ID using multiple sources
   * @param {string} assetId - Asset ID to look up
   * @returns {string} - Asset name or "Unknown"
   * @private
   */
  _getAssetName(assetId) {
    if (!assetId) return 'Unknown';
    
    // Try global map first (fastest)
    if (window.assetMap && window.assetMap[assetId]) {
      return window.assetMap[assetId].name || 'Unknown';
    }
    
    // Try AssetService next
    if (window.AssetService && typeof window.AssetService.getAssetName === 'function') {
      return window.AssetService.getAssetName(assetId);
    }
    
    // Try store as last resort
    const asset = window.taprootStore?.state?.assets?.find(a => a.asset_id === assetId);
    if (asset) {
      return asset.name || 'Unknown';
    }
    
    // Return a short version of the ID if all else fails
    return `Asset ${assetId.substring(0, 8)}...`;
  },
  
  /**
   * Process WebSocket payment update
   * @param {Object} data - Payment data from WebSocket
   * @returns {Object|null} - Processed payment or null
   */
  processWebSocketUpdate(data) {
    if (!data?.type || data.type !== 'payment_update' || !data.data) {
      return null;
    }
    
    // Make sure asset name is available
    if (data.data.asset_id) {
      this._ensureAssetNames([data.data]);
    }
    
    // Map the payment using DataUtils
    const payment = this._mapPayment(data.data);
    
    // Add to store
    if (payment) {
      window.taprootStore.actions.addPayment(payment);
    }
    
    return payment;
  }
};

// Export the service
window.PaymentService = PaymentService;
