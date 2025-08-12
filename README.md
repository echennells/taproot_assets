# Taproot Assets Extension for LNbits

A powerful extension for LNbits that enables Taproot Assets functionality, allowing you to issue, manage, and transfer Bitcoin-native digital assets using the Taproot Assets Protocol.

## Features

- **Asset Management**: List and view all Taproot Assets in your node
- **Send/Receive**: Create and pay Taproot Asset invoices
- **Channel Support**: View Lightning channels with Taproot Assets
- **Balance Tracking**: Monitor asset balances across all channels
- **Real-time Updates**: WebSocket support for live balance and transaction updates

## Requirements

- LNbits instance
- Access to a Taproot Assets daemon (tapd) either:
  - Integrated within [Lightning Terminal (litd)](https://github.com/lightninglabs/lightning-terminal) (recommended - bundles LND, Loop, Pool, Faraday, and Taproot Assets)
  - Running as a standalone service

## Installation

1. Clone this extension into your LNbits extensions directory:
   ```bash
   cd /path/to/lnbits/lnbits/extensions
   git clone https://github.com/echennells/taproot_assets.git
   ```
2. **Install Required gRPC Protocol Files** (see below)
3. Configure the connection settings (see Configuration section)
4. Restart LNbits

**For Docker deployments:** See [mutinynet-litd-lnbits](https://github.com/echennells/mutinynet-litd-lnbits) for a complete Docker Compose configuration example with Lightning Terminal and LNbits.

### Installing gRPC Protocol Files

This extension requires gRPC protocol buffer files for communication with LND and Taproot Assets daemon. These files are provided as compressed archives in the extension directory.

**Why these files are needed:** The gRPC files that ship with LNbits core don't include Taproot Assets support. These archives contain the updated protocol buffers with full Taproot Assets functionality.

**Method 1: Extract to LNbits wallets directory**
```bash
# Navigate to your LNbits root directory
cd /path/to/lnbits

# Extract LND gRPC files (if not already present)
tar -xzf lnbits/extensions/taproot_assets/lnd_grpc_files.tar.gz

# Extract Taproot Assets gRPC files
tar -xzf lnbits/extensions/taproot_assets/tapd_grpc_files.tar.gz
```

**Method 2: For Docker deployments**
Add extraction commands to your Dockerfile or entrypoint script:
```dockerfile
# Extract gRPC files during container build
RUN tar -xzf /app/lnbits/extensions/taproot_assets/lnd_grpc_files.tar.gz -C /app/
RUN tar -xzf /app/lnbits/extensions/taproot_assets/tapd_grpc_files.tar.gz -C /app/
```

**What these files provide:**
- `lnd_grpc_files.tar.gz`: Contains LND protocol buffers (lightning_pb2.py, invoices_pb2.py, router_pb2.py, etc.)
- `tapd_grpc_files.tar.gz`: Contains Taproot Assets protocol buffers (taprootassets_pb2.py, assetwallet_pb2.py, rfq_pb2.py, etc.)

These files enable the extension to communicate with:
- LND via gRPC (for Lightning network operations)
- Taproot Assets daemon via gRPC (for asset operations)
- RFQ (Request for Quote) services for asset trading
- Asset wallet operations for advanced asset management

## Configuration

The extension supports two connection modes:

### 1. Integrated Mode (Recommended for litd users)

If you're running litd with integrated tapd and LNbits is configured to use gRPC:

**docker-compose.yml:**
```yaml
environment:
  - LNBITS_BACKEND_WALLET_CLASS=LndGrpcWallet
  - LND_GRPC_ENDPOINT=lit
  - LND_GRPC_PORT=10009
  - LND_GRPC_CERT=/root/.lnd/tls.cert
  - LND_GRPC_MACAROON=/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon
```

**Note**: Integrated mode requires a macaroon with both LND and tapd permissions. If you encounter permission errors, use standalone mode instead.

### 2. Standalone Mode

For separate tapd instances or when LNbits uses REST:

**Option A: Environment Variables**
```yaml
environment:
  # LNbits config (can be REST or gRPC)
  - LNBITS_BACKEND_WALLET_CLASS=LndRestWallet
  - LND_REST_ENDPOINT=https://lit:8080
  - LND_REST_CERT=/root/.lnd/tls.cert
  - LND_REST_MACAROON=/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon
  
  # Taproot Assets config
  - TAPD_HOST=lit:10009
  - TAPD_TLS_CERT_PATH=/root/.lnd/tls.cert
  - TAPD_MACAROON_PATH=/root/.tapd/data/mainnet/admin.macaroon
```

**Option B: Configuration File**
1. Copy `taproot_assets.conf.example` to `taproot_assets.conf`
2. Update the settings with your paths and credentials
3. The config file takes precedence over environment variables

### Docker vs Local Paths

**Docker paths:**
- TLS cert: `/root/.lnd/tls.cert`
- LND macaroon: `/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon`
- tapd macaroon: `/root/.tapd/data/mainnet/admin.macaroon`

**Local paths:**
- TLS cert: `/home/[user]/.lnd/tls.cert`
- LND macaroon: `/home/[user]/.lnd/data/chain/bitcoin/mainnet/admin.macaroon`
- tapd macaroon: `/home/[user]/.tapd/data/mainnet/admin.macaroon`

## Connection Architecture

```
┌─────────────┐         ┌─────────────┐
│   LNbits    │         │    litd     │
│             │ REST    │             │
│  Wallet  ───┼────────►│ :8080 (LND) │
│             │         │             │
└─────────────┘         │             │
                        │             │
┌─────────────┐         │             │
│  Taproot    │ gRPC    │             │
│  Extension ─┼────────►│ :10009      │
│             │         │ (LND+tapd)  │
└─────────────┘         └─────────────┘
```

## Troubleshooting

### "Invalid macaroon" error
- In integrated mode: The LND macaroon doesn't have tapd permissions
- Solution: Use standalone mode with separate tapd credentials

### "No such file or directory" error
- Check that file paths are correct for your environment (Docker vs local)
- Ensure the tapd/lnd services are running and accessible

### Extension not loading
- Check LNbits logs: `docker logs [lnbits-container]`
- Verify all required services are running
- Ensure credentials have proper permissions

### "ModuleNotFoundError" or gRPC import errors
- Make sure you've extracted the gRPC protocol buffer files (see [Installing gRPC Protocol Files](#installing-grpc-protocol-files))
- The `lnd_grpc_files.tar.gz` and `tapd_grpc_files.tar.gz` must be extracted to the LNbits root directory
- These files provide the Python protocol buffer definitions needed for gRPC communication

## API Endpoints

- `GET /taproot_assets/api/v1/taproot/listassets` - List all assets
- `GET /taproot_assets/api/v1/taproot/asset-balances` - Get asset balances
- `POST /taproot_assets/api/v1/taproot/createinvoice` - Create asset invoice
- `POST /taproot_assets/api/v1/taproot/payinvoice` - Pay asset invoice
- `GET /taproot_assets/api/v1/taproot/payments` - List payments
- `GET /taproot_assets/api/v1/taproot/invoices` - List invoices

## WebSocket Support

Real-time updates are available via WebSocket connections:
- Balance updates: `/api/v1/ws/taproot-assets-balances-[user-id]`
- Payment updates: `/api/v1/ws/taproot-assets-payments-[user-id]`
- Invoice updates: `/api/v1/ws/taproot-assets-invoices-[user-id]`

## Development

### Project Structure
```
taproot_assets/
├── __init__.py           # Extension initialization
├── config.json           # Extension metadata
├── views.py              # Web routes
├── views_api.py          # API endpoints
├── models.py             # Data models
├── tapd/                 # Taproot daemon integration
│   ├── taproot_node.py   # Node connection management
│   ├── taproot_assets.py # Asset operations
│   └── ...               # Other tapd modules
└── static/               # Frontend assets
```

## License

MIT license