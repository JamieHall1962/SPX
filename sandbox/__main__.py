# sandbox/__main__.py
import os
import sys
import argparse
import tkinter as tk
import logging
from pathlib import Path

# Add the parent directory to sys.path to enable imports
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from sandbox.gui import OptionStrategySandboxGUI
from sandbox.strike_tester import StrikeTester, OptionChainSimulator
from utils.logging_utils import setup_logger

# Set up logger
logger = setup_logger("sandbox_main")

def launch_gui():
    """Launch the sandbox GUI"""
    logger.info("Launching SPX Option Strategy Sandbox GUI")
    root = tk.Tk()
    app = OptionStrategySandboxGUI(root)
    root.mainloop()

def run_test_suite(args):
    """Run automated test suite with predefined strategies"""
    logger.info("Running automated test suite")
    
    # Create option chain simulator and strike tester
    simulator = OptionChainSimulator(
        underlying_price=args.price,
        volatility=args.volatility / 100
    )
    tester = StrikeTester(simulator)
    
    # Run tests for Iron Condor
    if args.strategy == 'all' or args.strategy == 'ic':
        logger.info("Testing Iron Condor strategy")
        ic_results = tester.test_iron_condor(
            dte=14,
            put_delta=0.16,
            call_delta=0.16,
            wing_width=20
        )
        print("\nIron Condor Results:")
        print(f"Max Profit: ${ic_results.get('risk_reward', {}).get('max_profit', 0):.2f}")
        print(f"Max Loss: ${ic_results.get('risk_reward', {}).get('max_loss', 0):.2f}")
        print(f"Risk/Reward Ratio: {ic_results.get('risk_reward', {}).get('risk_reward_ratio', 0):.2f}")
    
    # Run tests for Double Calendar
    if args.strategy == 'all' or args.strategy == 'dc':
        logger.info("Testing Double Calendar strategy")
        dc_results = tester.test_double_calendar(
            short_dte=7,
            long_dte=21,
            put_delta=0.30,
            call_delta=0.30
        )
        print("\nDouble Calendar Results:")
        print(f"Max Profit: ${dc_results.get('risk_reward', {}).get('max_profit', 0):.2f}")
        print(f"Max Loss: ${dc_results.get('risk_reward', {}).get('max_loss', 0):.2f}")
        print(f"Risk/Reward Ratio: {dc_results.get('risk_reward', {}).get('risk_reward_ratio', 0):.2f}")
    
    # Run tests for Put Butterfly
    if args.strategy == 'all' or args.strategy == 'pb':
        logger.info("Testing Put Butterfly strategy")
        pb_results = tester.test_put_butterfly(
            dte=7,
            center_delta=0.30,
            wing_width=20
        )
        print("\nPut Butterfly Results:")
        print(f"Max Profit: ${pb_results.get('risk_reward', {}).get('max_profit', 0):.2f}")
        print(f"Max Loss: ${pb_results.get('risk_reward', {}).get('max_loss', 0):.2f}")
        print(f"Risk/Reward Ratio: {pb_results.get('risk_reward', {}).get('risk_reward_ratio', 0):.2f}")

def main():
    """Main entry point for the sandbox module"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="SPX Option Strategy Sandbox")
    parser.add_argument("--gui", action="store_true", help="Launch the graphical user interface")
    parser.add_argument("--test", action="store_true", help="Run automated test suite")
    parser.add_argument("--strategy", choices=['all', 'ic', 'dc', 'pb'], default='all',
                       help="Strategy to test (ic=Iron Condor, dc=Double Calendar, pb=Put Butterfly, all=All)")
    parser.add_argument("--price", type=float, default=4500.0, help="SPX price")
    parser.add_argument("--volatility", type=float, default=20.0, help="Implied volatility in percent")
    
    args = parser.parse_args()
    
    # If no arguments are provided, launch GUI by default
    if len(sys.argv) == 1 or args.gui:
        launch_gui()
    elif args.test:
        run_test_suite(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
