#!/usr/bin/env python3
"""Test script for Pontem faucet call with proper BCS serialization."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.config import Config
from src.wallet import WalletManager
from src.faucet import FaucetManager
from src.database import MetricsDB

async def test_pontem_faucet():
    """Test calling Pontem faucet for USDT."""
    # Load config
    config = Config.load()
    
    # Initialize database
    db = MetricsDB()
    
    # Initialize wallet
    wallet = WalletManager(config)
    
    # Initialize faucet manager with wallet and db
    faucet = FaucetManager(config, db, wallet)
    
    # Test address (our wallet)
    test_address = wallet.address
    print(f"Wallet address: {test_address}")
    
    # Pontem faucet address and USDT coin type
    faucet_addr = "0x43417434fd869edee76cca2a4d2301e528a1551b1d719b75c350c3c97d15b8b9"
    usdt_coin_type = "0x43417434fd869edee76cca2a4d2301e528a1551b1d719b75c350c3c97d15b8b9::coins::USDT"
    
    print(f"\nTesting Pontem faucet call:")
    print(f"  Faucet address: {faucet_addr}")
    print(f"  Coin type: {usdt_coin_type}")
    print(f"  Recipient: {test_address}")
    
    try:
        # Call the faucet
        tx_hash = await faucet.request_pontem_faucet(
            coin_type=usdt_coin_type,
            faucet_address=faucet_addr,
            recipient_address=test_address
        )
        print(f"\n✅ Success! Transaction hash: {tx_hash}")
        return True
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_pontem_faucet())
    sys.exit(0 if success else 1)
