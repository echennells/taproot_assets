> **Warning**
> This extension should only be used on testnet or mutinynet because it untested and currently uses the simplified RFQ process in litd which isn't intended to be used on mainnet

# LNbits Taproot Assets Extension

The Taproot Assets extension for LNbits provides integration with the Taproot Assets Protocol (TAP), allowing users to issue, transfer, and manage Taproot Assets directly through their LNbits interface.

## Overview

Taproot Assets is a Bitcoin Layer 2 protocol that enables the issuance and transfer of digital assets on the Bitcoin blockchain with high scalability, privacy, and fungibility. This extension connects with a Taproot Assets daemon (tapd) to allow LNbits users to:

- View their Taproot Assets and channel balances
- Create and pay invoices for Taproot Asset transfers
- Track transactions and payment history
- Manage and monitor Taproot Asset channels

## Features

- **Asset Management**: View and manage your Taproot Assets
- **Invoicing**: Create and settle invoices for Taproot Asset transfers
- **Payments**: Send Taproot Assets to other users or external recipients
- **Transaction Tracking**: Monitor your Taproot Asset transaction history
- **Channel Management**: View your Taproot Asset channel information
- **WebSocket Notifications**: Real-time updates for payments, invoices, and balance changes

## Requirements

- LNbits (latest version)
- Taproot Assets daemon (tapd)
- Lightning Network daemon (lnd)

## Installation 
- requires updated lnd and tapd protocol files, extract the two included .tar.gz files into the lnbits directory
- use the https://github.com/echennells/mutinynet-litd-lnbits repo to help you spin up a mutineynet instance 

  
