/**
 * Notification Service for Taproot Assets extension
 * Uses native LNbits notification methods
 * Updated to use the centralized store
 */

const NotificationService = {
  /**
   * Show a success notification
   * @param {string} message - Message to display
   */
  showSuccess(message) {
    if (window.LNbits && window.LNbits.utils && window.LNbits.utils.notifySuccess) {
      window.LNbits.utils.notifySuccess(message);
    } else if (window.Quasar) {
      window.Quasar.Notify.create({
        message: message,
        color: 'positive',
        icon: 'check_circle',
        timeout: 2000
      });
    } else {
      console.log('Success:', message);
    }
  },
  
  /**
   * Show an error notification
   * @param {string} message - Message to display
   */
  showError(message) {
    if (window.LNbits && window.LNbits.utils && window.LNbits.utils.notifyApiError) {
      // LNbits notifyApiError expects an error object with response.data.detail
      window.LNbits.utils.notifyApiError({
        response: {
          data: {
            detail: message
          }
        }
      });
    } else if (window.Quasar) {
      window.Quasar.Notify.create({
        message: message,
        color: 'negative',
        icon: 'error',
        timeout: 3000
      });
    } else {
      console.error('Error:', message);
    }
  },
  
  /**
   * Show a warning notification
   * @param {string} message - Message to display
   */
  showWarning(message) {
    if (window.LNbits && window.LNbits.utils && window.LNbits.utils.notify) {
      window.LNbits.utils.notify({
        message: message,
        type: 'warning'
      });
    } else if (window.Quasar) {
      window.Quasar.Notify.create({
        message: message,
        color: 'warning',
        icon: 'warning',
        timeout: 3000
      });
    } else {
      console.warn('Warning:', message);
    }
  },
  
  /**
   * Show an info notification
   * @param {string} message - Message to display
   */
  showInfo(message) {
    if (window.LNbits && window.LNbits.utils && window.LNbits.utils.notify) {
      window.LNbits.utils.notify({
        message: message,
        type: 'info'
      });
    } else if (window.Quasar) {
      window.Quasar.Notify.create({
        message: message,
        color: 'info',
        icon: 'info',
        timeout: 3000
      });
    } else {
      console.info('Info:', message);
    }
  },
  
  /**
   * Show loading with message
   * @param {string} message - Message to display
   */
  showLoading(message = 'Loading...') {
    // In LNbits, there's no standard loading indicator
    // Log the loading message for now
    console.log('Loading started:', message);
  },
  
  /**
   * Hide loading indicator
   */
  hideLoading() {
    // In LNbits, there's no standard loading indicator
    // Log that loading has finished
    console.log('Loading finished');
  },
  
  /**
   * Notify user about an invoice being created
   * @param {Object} invoice - Created invoice data
   */
  notifyInvoiceCreated(invoice) {
    // Notification removed as requested
    // No need to update store as the InvoiceService already did this
  },
  
  /**
   * Notify user about an invoice being paid
   * @param {Object} invoice - Paid invoice data
   */
  notifyInvoicePaid(invoice) {
    const assetName = invoice.asset_name || taprootStore.getters.getAssetName(invoice.asset_id) || 'Unknown Asset';
    const amount = invoice.asset_amount || 0;
    
    this.showSuccess(`Invoice Paid: ${amount} ${assetName}`);
    
    // Update the invoice in the store if we have an ID
    if (invoice.id) {
      taprootStore.actions.updateInvoice(invoice.id, { 
        status: 'paid',
        paid_at: new Date().toISOString()
      });
    }
    
    // Refresh assets to update balances
    const wallet = taprootStore.getters.getCurrentWallet();
    if (wallet) {
      AssetService.getAssets(wallet);
    }
    
    // Check if we should close the invoice dialog
    if (window.app && window.app.createdInvoiceDialog && window.app.createdInvoiceDialog.show && window.app.createdInvoice) {
      console.log('Checking if we should close the invoice dialog...');
      
      // Try multiple ways to match the invoice
      let matchFound = false;
      
      // Match by ID
      if (window.app.createdInvoice.id === invoice.id) {
        console.log('Match found by invoice ID');
        matchFound = true;
      }
      // Match by payment hash
      else if (window.app.createdInvoice.payment_hash === invoice.payment_hash) {
        console.log('Match found by payment hash');
        matchFound = true;
      }
      
      // If the displayed invoice is the one that was paid, close the dialog
      if (matchFound) {
        console.log('CLOSING INVOICE DIALOG - Match found between displayed invoice and paid invoice');
        // Close the dialog
        window.app.createdInvoiceDialog.show = false;
        
        // Show a notification
        this.showSuccess('Invoice has been paid');
      } else {
        console.log('Not closing dialog - displayed invoice does not match the paid one');
      }
    }
  },
  
  /**
   * Notify user about payment being sent
   * @param {Object} paymentResult - Payment result data
   */
  notifyPaymentSent(paymentResult) {
    let title, message;
    
    // Customize based on payment type
    if (paymentResult.internal_payment) {
      title = 'Internal Payment Processed';
      message = 'Payment to another user on this node has been processed successfully.';
    } else {
      title = 'Payment Successful!';
      message = 'Payment has been sent successfully.';
    }
    
    this.showSuccess(message);
    
    // Return formatted message for display in dialogs
    return { title, message };
  },
  
  /**
   * Show copy notification
   * @param {string} itemName - Name of the item that was copied
   */
  notifyCopied(itemName = 'Item') {
    this.showSuccess(`${itemName} copied to clipboard`);
  },
  
  /**
   * Process and display API error
   * @param {Object} error - Error object from API
   * @param {string} fallbackMessage - Fallback message if no error details
   * @returns {string} - Processed error message
   */
  processApiError(error, fallbackMessage = 'An error occurred') {
    let errorMessage = fallbackMessage;
    
    // Try to extract meaningful error message
    if (error) {
      if (error.isApiError && error.message) {
        errorMessage = error.message;
      } else if (error.response && error.response.data) {
        if (error.response.data.detail) {
          errorMessage = error.response.data.detail;
        } else if (error.response.data.message) {
          errorMessage = error.response.data.message;
        }
      } else if (error.message) {
        errorMessage = error.message;
      }
    }
    
    this.showError(errorMessage);
    return errorMessage;
  }
};

// Export the service
window.NotificationService = NotificationService;
