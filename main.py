#!/usr/bin/env python3
# main.py - Main entry point for SPX Trader application
import os
import sys
import time
import argparse
import logging
import signal
import threading
from datetime import datetime

# Import our own modules
from core.tws_connector import TWS
from core.trade_engine import TradeEngine
from config.settings import (
    TRADING_ACTIVE, DEBUG_MODE, SANDBOX_MODE, 
    TWS_HOST, TWS_PORT, TWS_CLIENT_ID
)
from config.trade_config import active_strategies
from utils.logging_utils import setup_logger
from utils.notifications import notify_status_update, notify_error

# Set up logger
logger = setup_logger("main")

# Global variables for clean shutdown
running = True
trade_engine = None
tws_connector = None

def signal_handler(sig, frame):
    """Handle Ctrl+C and other termination signals"""
    global running
    logger.info("Shutdown signal received, stopping...")
    running = False

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="SPX Options Trader")
    parser.add_argument("--sandbox", action="store_true", help="Run in sandbox mode (no real trades)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--port", type=int, default=TWS_PORT, help="TWS/IB Gateway port")
    parser.add_argument("--client-id", type=int, default=TWS_CLIENT_ID, help="TWS client ID")
    parser.add_argument("--monitor", action="store_true", help="Monitor mode (no trades, just watch)")
    parser.add_argument("--test-connection", action="store_true", help="Test TWS connection and exit")
    
    return parser.parse_args()

def connect_to_tws(args):
    """Connect to TWS/IB Gateway"""
    global tws_connector
    
    logger.info(f"Connecting to TWS at {TWS_HOST}:{args.port} with client ID {args.client_id}")
    
    # Create TWS connector
    tws_connector = TWS()
    
    # Try to connect
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        logger.info(f"Connection attempt {attempt}/{max_attempts}")
        
        if tws_connector.connect(TWS_HOST, args.port, args.client_id):
            logger.info("Successfully connected to TWS")
            return True
        
        if attempt < max_attempts:
            logger.warning(f"Connection failed, retrying in 5 seconds...")
            time.sleep(5)
    
    logger.error("Failed to connect to TWS after multiple attempts")
    return False

def initialize_trade_engine():
    """Initialize the trade engine"""
    global trade_engine, tws_connector
    
    logger.info("Initializing trade engine")
    
    # Create trade engine
    trade_engine = TradeEngine(tws_connector)
    
    # Add active strategies
    for strategy in active_strategies:
        trade_engine.add_strategy(strategy)
    
    logger.info(f"Added {len(active_strategies)} active strategies")
    
    return True

def run_trading_session(args):
    """Run the main trading session"""
    global running, trade_engine
    
    # Set sandbox/debug mode from args if specified
    sandbox_mode = SANDBOX_MODE
    debug_mode = DEBUG_MODE
    
    if args.sandbox:
        sandbox_mode = True
    
    if args.debug:
        debug_mode = True
    
    # Log mode settings
    logger.info(f"Trading active: {TRADING_ACTIVE}")
    logger.info(f"Sandbox mode: {sandbox_mode}")
    logger.info(f"Debug mode: {debug_mode}")
    
    if args.monitor:
        logger.info("Running in MONITOR mode - no trades will be executed")
    
    # Send notification that system is starting
    status_message = f"SPX Trader starting up in {'SANDBOX' if sandbox_mode else 'LIVE'} mode"
    notify_status_update(status_message)
    
    # Start the trade engine if not in test mode
    if not args.test_connection:
        if not initialize_trade_engine():
            logger.error("Failed to initialize trade engine")
            return False
        
        # Start the trade engine
        if not args.monitor:
            trade_engine.start()
            logger.info("Trade engine started")
        else:
            logger.info("Monitor mode - trade engine not started")
    
    # Main loop
    try:
        while running:
            # Check TWS connection
            if not tws_connector.is_connected():
                logger.warning("TWS connection lost, attempting to reconnect")
                if not tws_connector.reconnect():
                    logger.error("Failed to reconnect to TWS, shutting down")
                    running = False
                    break
            
            # In test mode, we just exit after confirming connection
            if args.test_connection:
                logger.info("Connection test successful, exiting")
                running = False
                break
            
            # Sleep to avoid high CPU usage
            time.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down")
    except Exception as e:
        logger.exception(f"Error in main loop: {e}")
        notify_error(f"Error in main loop: {e}")
    
    finally:
        # Perform cleanup
        if trade_engine is not None and not args.monitor and not args.test_connection:
            logger.info("Stopping trade engine")
            trade_engine.stop()
        
        if tws_connector is not None:
            logger.info("Disconnecting from TWS")
            tws_connector.disconnect()
        
        logger.info("SPX Trader shutdown complete")
        notify_status_update("SPX Trader shutdown complete")
    
    return True

def main():
    """Main entry point"""
    # Parse command line arguments
    args = parse_arguments()
    
    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("SPX Trader starting up")
    
    # Connect to TWS
    if not connect_to_tws(args):
        logger.error("Failed to connect to TWS, exiting")
        return 1
    
    # Run the trading session
    if not run_trading_session(args):
        logger.error("Trading session failed")
        return 1
    
    logger.info("SPX Trader completed successfully")
    return 0

if __name__ == "__main__":
    sys.exit(main())
