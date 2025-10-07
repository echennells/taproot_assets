/**
 * Consolidated Data Utilities for Taproot Assets extension
 * Combines all common utility functions in one place
 */

const DataUtils = {
  /**
   * Format a transaction date consistently
   * @param {string|Date} dateStr - Date string or object to format
   * @returns {string} - Formatted date string
   */
  formatDate(dateStr) {
    try {
      const date = dateStr instanceof Date ? dateStr : new Date(dateStr);
      // Quasar is always available in the LNbits environment, so we can just use it directly
      return window.Quasar.date.formatDate(date, 'YYYY-MM-DD HH:mm:ss');
    } catch (e) {
      console.error('Error formatting date:', e);
      return dateStr || 'Unknown date';
    }
  },
  
  /**
   * Calculate relative time from date (e.g. "2 hours ago")
   * @param {string|Date} dateStr - Date string or object 
   * @returns {string} - Relative time string
   */
  getRelativeTime(dateStr) {
    try {
      const date = dateStr instanceof Date ? dateStr : new Date(dateStr);
      const now = new Date();
      const diffMs = now - date;
      
      if (diffMs < 60000) { // less than a minute
        return 'a minute ago';
      } else if (diffMs < 3600000) { // less than an hour
        const mins = Math.floor(diffMs / 60000);
        return `${mins} minute${mins > 1 ? 's' : ''} ago`;
      } else if (diffMs < 86400000) { // less than a day
        const hours = Math.floor(diffMs / 3600000);
        return `${hours} hour${hours > 1 ? 's' : ''} ago`;
      } else if (diffMs < 604800000) { // less than a week
        const days = Math.floor(diffMs / 86400000);
        return `${days} day${days > 1 ? 's' : ''} ago`;
      }
      
      // Just use formatted date for older items
      return this.formatDate(date);
    } catch (e) {
      console.error('Error calculating relative time:', e);
      return 'Unknown time';
    }
  },
  
  /**
   * Shortify a long string (e.g. payment hash)
   * @param {string} text - Text to shorten
   * @param {number} maxLength - Maximum length (default 10)
   * @returns {string} - Shortened text with ellipsis
   */
  shortify(text, maxLength = 10) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    
    const half = Math.floor(maxLength / 2);
    return `${text.substring(0, half)}...${text.substring(text.length - half)}`;
  },
  
  /**
   * Get CSS color class for a transaction status
   * @param {string} status - Transaction status
   * @returns {string} - CSS color class
   */
  getStatusColor(status) {
    switch (status) {
      case 'paid':
      case 'completed':
        return 'positive';
      case 'pending':
        return 'warning';
      case 'expired':
        return 'negative';
      default:
        return 'grey';
    }
  },
  
  /**
   * Format channel balance from base units to display units
   * Used ONLY for channel balances (local_balance, remote_balance) from LND
   * @param {number|string} baseUnits - Balance in base units from LND
   * @param {number} decimalDisplay - Number of decimal places from asset definition
   * @returns {string} - Formatted balance with proper decimal placement
   */
  formatChannelBalance(baseUnits, decimalDisplay = 0) {
    if (baseUnits === undefined || baseUnits === null) return '0';

    // Convert to number if string
    const amount = typeof baseUnits === 'string' ? parseFloat(baseUnits) : baseUnits;
    if (isNaN(amount)) return '0';

    // Cap decimal places at 2 maximum
    const displayDecimals = Math.min(decimalDisplay, 2);

    // If no decimal places, just format with commas
    if (displayDecimals === 0) {
      return amount.toLocaleString();
    }

    // Apply decimal places by dividing by 10^decimalDisplay (but display with capped decimals)
    const divisor = Math.pow(10, decimalDisplay);
    const displayAmount = amount / divisor;

    // Format with proper decimal places and thousands separators (capped at 2)
    return displayAmount.toLocaleString(undefined, {
      minimumFractionDigits: displayDecimals,
      maximumFractionDigits: displayDecimals
    });
  },

  /**
   * Format asset amount that's already in display units
   * Used for amounts from backend (invoices, payments, balances)
   * @param {number|string} displayUnits - Amount already in display units
   * @param {number} decimalDisplay - Number of decimal places for formatting
   * @returns {string} - Formatted amount with commas and proper decimals
   */
  formatAssetBalance(displayUnits, decimalDisplay = 0) {
    if (displayUnits === undefined || displayUnits === null) return '0';

    // Convert to number if string
    const amount = typeof displayUnits === 'string' ? parseFloat(displayUnits) : displayUnits;
    if (isNaN(amount)) return '0';

    // Cap decimal places at 2 maximum
    const displayDecimals = Math.min(decimalDisplay, 2);

    // Just format with the appropriate decimal places (no conversion needed)
    if (displayDecimals === 0) {
      return amount.toLocaleString();
    }

    return amount.toLocaleString(undefined, {
      minimumFractionDigits: displayDecimals,
      maximumFractionDigits: displayDecimals
    });
  },
  
  /**
   * Parse asset value from any format to a number
   * @param {number|string} value - Value to parse
   * @returns {number} - Parsed numeric value
   */
  parseAssetValue(value) {
    if (!value) return 0;

    if (typeof value === 'string') {
      const cleanValue = value.replace(/[^0-9.]/g, '');
      return parseFloat(cleanValue) || 0;
    }

    return typeof value === 'number' ? (isNaN(value) ? 0 : value) : 0;
  },

  /**
   * Convert display amount to base units for API calls
   * @param {number|string} displayAmount - Amount in display units (what user sees)
   * @param {number} decimalDisplay - Number of decimal places from asset definition
   * @returns {number} - Amount in base units (for API/backend)
   */
  convertToBaseUnits(displayAmount, decimalDisplay = 0) {
    if (displayAmount === undefined || displayAmount === null) return 0;

    const amount = typeof displayAmount === 'string' ? parseFloat(displayAmount) : displayAmount;
    if (isNaN(amount)) return 0;

    // If no decimal places, return as is
    if (decimalDisplay === 0) {
      return Math.round(amount);
    }

    // Multiply by 10^decimalDisplay to convert to base units
    const multiplier = Math.pow(10, decimalDisplay);
    return Math.round(amount * multiplier);
  },
  
  /**
   * Copy text to clipboard
   * @param {string} text - Text to copy
   * @param {Function|string} notifyCallback - Callback for notification or message string
   * @returns {boolean} - Whether copy was successful
   */
  copyText(text, notifyCallback) {
    if (!text) {
      if (typeof notifyCallback === 'function') {
        notifyCallback({
          message: 'Nothing to copy',
          color: 'warning',
          icon: 'warning',
          timeout: 1000
        });
      } else if (typeof notifyCallback === 'string' && window.LNbits?.utils?.notify) {
        window.LNbits.utils.notify({ 
          message: 'Nothing to copy',
          type: 'warning'
        });
      }
      return false;
    }
    
    try {
      // LNbits environment always has Quasar available, so use it directly
      window.Quasar.copyToClipboard(text)
        .then(() => {
          if (typeof notifyCallback === 'function') {
            notifyCallback({
              message: 'Copied to clipboard',
              color: 'positive',
              icon: 'check',
              timeout: 1000
            });
          } else if (typeof notifyCallback === 'string' && window.LNbits?.utils?.notifySuccess) {
            window.LNbits.utils.notifySuccess(notifyCallback);
          } else if (window.LNbits?.utils?.notifySuccess) {
            window.LNbits.utils.notifySuccess('Copied to clipboard');
          }
        })
        .catch(err => {
          console.error('Failed to copy text:', err);
          if (typeof notifyCallback === 'function') {
            notifyCallback({
              message: 'Failed to copy to clipboard',
              color: 'negative',
              icon: 'error',
              timeout: 1000
            });
          } else if (window.LNbits?.utils?.notifyApiError) {
            window.LNbits.utils.notifyApiError('Failed to copy to clipboard');
          }
        });
      
      return true;
    } catch (error) {
      console.error('Failed to copy text:', error);
      
      if (typeof notifyCallback === 'function') {
        notifyCallback({
          message: 'Failed to copy to clipboard',
          color: 'negative',
          icon: 'error',
          timeout: 1000
        });
      } else if (window.LNbits?.utils?.notifyApiError) {
        window.LNbits.utils.notifyApiError('Failed to copy to clipboard');
      }
      
      return false;
    }
  },
  
  /**
   * Combine and sort transactions (invoices and payments)
   * @param {Array} invoices - Array of invoices
   * @param {Array} payments - Array of payments
   * @returns {Array} - Combined and sorted transactions
   */
  combineTransactions(invoices, payments) {
    // Using the array constructor directly to create empty arrays is cleaner
    const safeInvoices = Array.isArray(invoices) ? invoices : [];
    const safePayments = Array.isArray(payments) ? payments : [];
    
    // Map each transaction to ensure proper formatting
    const mappedInvoices = safeInvoices.map(invoice => this.mapTransaction(invoice, 'invoice'));
    const mappedPayments = safePayments.map(payment => this.mapTransaction(payment, 'payment'));
    
    // Combine and sort by date (most recent first)
    return [...mappedInvoices, ...mappedPayments].sort((a, b) => {
      return new Date(b.created_at) - new Date(a.created_at);
    });
  },
  
  /**
   * Map a transaction (invoice or payment) to a standardized format
   * @param {Object} transaction - Transaction to map
   * @param {string} type - Transaction type ('invoice' or 'payment')
   * @returns {Object} - Mapped transaction
   */
  mapTransaction(transaction, type) {
    if (!transaction) return null;
    
    // Create a clean copy
    const mapped = {...transaction};
    
    // Set type and direction
    mapped.type = type || (transaction.payment_hash ? 'invoice' : 'payment');
    mapped.direction = mapped.type === 'invoice' ? 'incoming' : 'outgoing';
    
    // Format date consistently 
    if (mapped.created_at) {
      try {
        mapped.date = this.formatDate(mapped.created_at);
        mapped.timeFrom = this.getRelativeTime(mapped.created_at);
      } catch (e) {
        console.error('Error formatting date:', e);
        mapped.date = 'Unknown';
        mapped.timeFrom = 'Unknown';
      }
    }
    
    // Map description to memo for frontend consistency
    // The backend uses 'description' but frontend expects 'memo'
    if (mapped.description && !mapped.memo) {
      mapped.memo = mapped.description;
    }
    
    // Ensure extra exists and contains asset info
    mapped.extra = mapped.extra || {};
    
    if (mapped.type === 'invoice') {
      // For invoices
      if (!mapped.extra.asset_amount && mapped.asset_amount) {
        mapped.extra.asset_amount = mapped.asset_amount;
      }
      
      if (!mapped.extra.asset_id && mapped.asset_id) {
        mapped.extra.asset_id = mapped.asset_id;
      }
    } else {
      // For payments
      mapped.extra = {
        asset_amount: mapped.asset_amount,
        asset_id: mapped.asset_id,
        fee_sats: mapped.fee_sats
      };
    }
    
    return mapped;
  },
  
  /**
   * Filter combined transactions based on criteria
   * @param {Array} transactions - Combined transactions to filter
   * @param {Object} filters - Filter criteria
   * @param {Object} searchData - Search criteria
   * @param {Object} dateRange - Date range for filtering
   * @returns {Array} - Filtered transactions
   */
  filterTransactions(transactions, filters, searchData, dateRange) {
    if (!transactions || !Array.isArray(transactions)) {
      return [];
    }
    
    let result = [...transactions];
    
    // Apply direction filter
    if (filters?.direction && filters.direction !== 'all') {
      result = result.filter(tx => tx.direction === filters.direction);
    }
    
    // Apply status filter
    if (filters?.status && filters.status !== 'all') {
      result = result.filter(tx => tx.status === filters.status);
    }
    
    // Apply search text filter
    if (searchData?.searchText) {
      const searchLower = searchData.searchText.toLowerCase();
      result = result.filter(tx => 
        (tx.memo && tx.memo.toLowerCase().includes(searchLower)) ||
        (tx.payment_hash && tx.payment_hash.toLowerCase().includes(searchLower))
      );
    }
    
    // Apply date range filter
    if (dateRange && (dateRange.from || dateRange.to)) {
      result = result.filter(tx => {
        const txDate = new Date(tx.created_at);
        let matches = true;
        
        if (dateRange.from) {
          const fromDate = new Date(dateRange.from);
          fromDate.setHours(0, 0, 0, 0);
          if (txDate < fromDate) matches = false;
        }
        
        if (matches && dateRange.to) {
          const toDate = new Date(dateRange.to);
          toDate.setHours(23, 59, 59, 999);
          if (txDate > toDate) matches = false;
        }
        
        return matches;
      });
    }
    
    return result;
  },
  
  /**
   * Generate CSV content and trigger download
   * @param {Array} rows - Array of objects to convert to CSV
   * @param {string} filename - Filename for download
   * @param {Function} notifyCallback - Optional notification callback
   */
  downloadCSV(rows, filename, notifyCallback) {
    if (!rows || rows.length === 0) {
      if (notifyCallback) {
        notifyCallback({
          message: 'No data to export',
          color: 'warning',
          timeout: 2000
        });
      } else if (window.LNbits?.utils?.notify) {
        window.LNbits.utils.notify({
          message: 'No data to export',
          type: 'warning'
        });
      }
      return false;
    }
    
    try {
      // Get headers from first row
      const headers = Object.keys(rows[0]);
      
      // Create CSV content
      let csvContent = headers.join(',') + '\n';
      
      // Add rows
      rows.forEach(row => {
        const csvRow = headers.map(header => {
          // Handle values that might contain commas or quotes
          const value = row[header] !== undefined && row[header] !== null ? row[header].toString() : '';
          if (value.includes(',') || value.includes('"') || value.includes('\n')) {
            // Properly escape quotes by doubling them and wrap in quotes
            return '"' + value.replace(/"/g, '""') + '"';
          }
          return value;
        });
        csvContent += csvRow.join(',') + '\n';
      });
      
      // Create download link
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.setAttribute('href', url);
      link.setAttribute('download', filename);
      link.style.visibility = 'hidden';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      
      if (notifyCallback) {
        notifyCallback({
          message: 'Data exported successfully',
          color: 'positive',
          icon: 'check_circle',
          timeout: 2000
        });
      } else if (window.LNbits?.utils?.notifySuccess) {
        window.LNbits.utils.notifySuccess('Data exported successfully');
      }
      
      return true;
    } catch (error) {
      console.error('Error generating CSV:', error);
      
      if (notifyCallback) {
        notifyCallback({
          message: 'Failed to export data',
          color: 'negative',
          icon: 'error',
          timeout: 2000
        });
      } else if (window.LNbits?.utils?.notifyApiError) {
        window.LNbits.utils.notifyApiError('Failed to export data');
      }
      
      return false;
    }
  }
};

// Export the utilities
window.DataUtils = DataUtils;
