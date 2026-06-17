#!/usr/bin/env python3
"""Test script for DEX swap module."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import Config
from wallet import WalletManager
from database import MetricsDB
from activity_dex_swap import DexSwapModule

async def test_dex():
    """Test DEX swap functionality."""
    # Load config
    config = Config.load()
    print(f"Network: {config.network}")
    print(f"Router: {config.contracts.liquidswap_router}")
    
    # Initialize components
    wallet = WalletManager(config)
    db = MetricsDB(config.metrics.db_path)
    dex = DexSwapModule(config, wallet, db)
    
    print(f"Wallet address: {wallet.address}")
    balance = await wallet.get_balance()
    print(f"Balance: {balance} APT ({int(balance * 100_000_000)} octas)")
    
    # Test building transaction
    print("\nBuilding transaction...")
    try:
        entry_func = dex._build_entry_function(
            dex.swap_from_token,
            dex.swap_to_token,
            dex.swap_amount,
            int(dex.swap_amount * 4_000_000 / 100_000_000 * dex.min_amount_factor)
        )
        print(f"Entry function built successfully:")
        print(f"  Module: {entry_func.module}")
        print(f"  Function: {entry_func.function}")
        print(f"  Type args: {[str(t) for t in entry_func.type_args]}")
        print(f"  Args: {entry_func.args}")
    except Exception as e:
        print(f"ERROR building entry function: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Test simulation
    print("\nSimulating transaction...")
    try:
        success, results, error = await wallet.simulate_transaction(entry_func)
        if success:
            print(f"Simulation succeeded: {results}")
        else:
            print(f"Simulation failed: {error}")
    except Exception as e:
        print(f"ERROR during simulation: {e}")
        import traceback
        traceback.print_exc()
    
    # Test actual swap (commented out to avoid real transaction)
    # print("\nRunning swap...")
    # result = await dex.run()
    # print(f"Swap result: {result}")
    
    await wallet.close()

if __name__ == "__main__":
    asyncio.run(test_dex())
