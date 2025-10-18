# Release Notes - v1.2.0

## Highlights

### Critical Fixes
- **RFQ Rate Calculation**: Fixed oracle coefficient interpretation from millisats to centisats (/1000 → /100), resolving 10x underpricing issue in Bitcoin Switch LNURL payments
- **Payment Asset ID**: Fixed asset_id fallback logic to prevent balance mismatches when client doesn't provide asset_id in request
- **Decimal Display**: Fixed decimal_display extraction from protobuf objects and proper formatting across UI

### New Features
- **LNURL Asset Detection**: Parse asset support from callback URL parameters (`supports_assets=true`, `asset_ids`) for Bitcoin Switch compatibility
- **Improved Formatting**: Proper decimal display for asset amounts (e.g., 955.034 for 3-decimal assets, 99,149 for whole numbers)

### Security
- **LNURL Validation**: Added `check_callback_url()` validation to prevent SSRF attacks via malicious callback URLs

---

Generated: 2025-10-17
