# SPX Options Trading System

An automated options trading system built with Python and Interactive Brokers TWS API. The system executes complex options strategies with configurable parameters and risk management.

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![PyQt Version](https://img.shields.io/badge/PyQt-6.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-blue)

## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [System Architecture](#system-architecture)
- [Future Improvements](#future-improvements)
- [Contributing](#contributing)

## Overview

This system provides a robust foundation for automated options trading with Interactive Brokers, combining real-time monitoring, scheduled execution, and risk management in a user-friendly interface.

## Features

### Core Components

#### 1. Trading Dashboard (`ui/dashboard.py`)
- Main GUI application built with PyQt6
- Real-time monitoring of:
  - Connection status
  - Market hours
  - SPX and ES prices
  - Upcoming scheduled trades
  - System uptime
  - Trade history
- System startup/shutdown controls
- Emergency stop functionality

#### 2. Trade Execution (`trading/executor.py`)
- Multiple options strategies:
  - Double Calendar spreads
  - Iron Condors
  - Put/Call Butterflies
  - Custom strangles
- Configurable trade parameters
- Risk management controls
- Order monitoring and fill confirmation

#### 3. Trade Management (`trading/manager.py`)
- Centralized trading system control
- Active trade monitoring
- Position tracking
- P&L monitoring
- Risk metrics calculation

#### 4. Option Finding (`trading/option_finder.py`)
- Delta-based option selection
- Implied volatility calculations
- Market hours determination
- Price level analysis

#### 5. Trade Scheduling (`trading/scheduler.py`)
- Scheduled trade execution
- Market hours awareness
- Holiday calendar integration
- Multiple schedule support

#### 6. TWS Connection (`connection/tws_manager.py`)
- Interactive Brokers TWS API integration
- Market data management
- Order routing
- Connection stability monitoring
- Auto-reconnection capability

#### 7. Trade Database (`trading/database.py`)
- SQLite-based trade history
- Performance tracking
- Trade analytics
- Position monitoring

## Installation

1. Clone the repository:  
git clone https://github.com/yourusername/spx-options-trading.git

2. Install required packages:
```bash
pip install -r requirements.txt
```

3. Install Interactive Brokers TWS or Gateway

## Configuration

1. Configure TWS/Gateway:
   - Enable API connections
   - Set port number (default: 7497)
   - Configure market data subscriptions

2. Update configuration files:
   - Copy `config/config_example.py` to `config/config.py`
   - Set your TWS connection parameters
   - Configure trading parameters

## Usage

1. Start TWS/Gateway and log in

2. Launch the trading system:
```bash
python main.py
```

3. Use the dashboard to:
   - Monitor market conditions
   - View scheduled trades
   - Track active positions
   - Monitor system status

## System Architecture

```
project/
├── config/          # Configuration settings
├── connection/      # TWS API connection management
├── trading/         # Core trading logic
├── ui/             # User interface components
└── utils/          # Utility functions
```

## Future Improvements

1. Additional Features
   - More trading strategies
   - Advanced risk management
   - Performance analytics
   - Market analysis tools

2. Technical Improvements
   - Enhanced error handling
   - Comprehensive logging
   - Unit test coverage
   - Documentation updates

3. User Interface
   - Additional monitoring views
   - Custom alerts
   - Strategy visualization
   - Performance reporting

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.