# Core Files - DO NOT MODIFY WITHOUT EXPLICIT INSTRUCTION

## trade_config.py
Contains all trade configurations. Only modify when:
- Adding new trade strategies
- Adjusting existing trade parameters upon request
- Fixing critical bugs (with approval)

## tws_manager.py
Contains core TWS connectivity. Only modify when:
- Adding new essential TWS functionality
- Fixing critical bugs (with approval)
- Adding required error handling

### Essential TWS Methods
These methods must ALWAYS exist and maintain their core functionality:

OptionPosition class:
- Represents option position data structure
- Added: 2025-02-10

ConnectionManager:
- __init__() - Initialize connection manager
- get_tws() - Get TWS interface
- connect() - Connect to TWS
- disconnect() - Disconnect from TWS
- is_connected() - Check connection status
- request_market_data() - Subscribe to market data
- add_market_callback() - Register market data listener
- remove_market_callback() - Remove market data listener
- add_status_callback() - Register connection status listener
- remove_status_callback() - Remove connection status listener

IBWrapper:
- __init__() - Initialize wrapper
- set_client() - Set client reference
- tickPrice() - Handle price updates
- error() - Handle TWS errors
- _notify_callbacks() - Notify registered callbacks

## When to Request Changes
1. New feature requires core modification
2. Bug found in core functionality
3. Performance improvement needed
4. New trade strategy needs core support

## Change Process
1. Document the need for change
2. Get explicit approval
3. Make minimal required changes
4. Test thoroughly
5. Document all changes

## Process for Changes
1. ALWAYS check this document before modifying any core files
2. Get explicit approval for ANY changes to core components
3. Document the change in git commit message
4. Update this document if new core components are added

## How to Use This Document
1. Keep it open while working
2. Reference it before ANY changes
3. If unsure, ask before modifying
4. Update it when core components change (with approval)

## Recently Added Core Components
Keep track of when core components are added or modified:

1. 2025-02-10: Added OptionPosition class to tws_manager.py

### config/trade_config.py
Trade configurations - DO NOT MODIFY without explicit instruction: