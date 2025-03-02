# SPX Options Trader

A Python application for analyzing and trading SPX options with a focus on Iron Condor strategies based on delta targets.

## Overview

SPX Options Trader provides a powerful, user-friendly interface for options traders. It connects to Interactive Brokers (IBKR) to retrieve real-time market data and perform automated trading based on configurable strategies.

### Key Features

- Real-time SPX options chain data with accurate Greeks
- Delta-based Iron Condor strategy implementation
- Trade simulation and analytics
- Position monitoring and risk management
- Simple graphical user interface

## Architecture

The application follows a modular design:

- **Core**: Core functionality including IBKR connectivity and data processing
- **Strategies**: Trading strategy implementations
- **Utils**: Utility functions and helpers
- **UI**: User interface components
- **Config**: Configuration settings
- **Logs**: Application logs
- **Tests**: Test scripts and utilities

## Installation

### Prerequisites

- Python 3.9 or higher
- Interactive Brokers TWS or IB Gateway
- IBKR account (paper trading account is sufficient for testing)

### Setup

1. Clone the repository:
   ```
   git clone https://github.com/JamieHall1962/SPX.git
   cd SPX
   git checkout refactor
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   ```

3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`

4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

5. Configure IBKR connection settings in `config/ibkr_config.py`

## Usage

### Testing Connection

Before running the main application, verify your IBKR connection:
