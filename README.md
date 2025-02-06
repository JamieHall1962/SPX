# SPX Options Trading System

An automated options trading system built with Python and Interactive Brokers TWS API.

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

#### 1. Trading Dashboard (dashboard.py)
- Main GUI application built with PyQt6
- Provides real-time monitoring of:
  - Connection status
  - Market hours
  - SPX and ES prices
  - Upcoming scheduled trades
  - System uptime
  - Trade history
- Handles system startup/shutdown and emergency stops

#### 2. Trade Execution
- Supports multiple trade strategies:
  - Put Butterfly (`execute_put_fly`)
  - Double Calendar spreads
  - Iron Condors
  - Custom strangles
- Each strategy has configurable parameters via `TradeConfig` objects

#### 3. Trade Scheduling (trade_scheduler.py)
- Manages scheduled trade execution
- Supports day-specific and time-specific scheduling
- Handles market hours and holiday calendars

#### 4. TWS Connection (tws_connector.py)
- Manages Interactive Brokers TWS API connection
- Handles market data requests
- Processes order submissions and monitoring
- Implements connection recovery and stability features

#### 5. Trade Database (trade_database.py)
- Records trade history and performance
- Stores execution details and P&L

#### 6. Market Analysis (find_delta.py)
- Calculates option greeks and implied volatility
- Finds specific delta options
- Determines market hours and conditions

## Installation
