# sandbox/gui.py
import os
import sys
from pathlib import Path

# Add the parent directory to sys.path to enable imports
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Now we can import modules from parent directories
import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
import pandas as pd
import threading
import json
import os
from datetime import datetime
import time
import requests

from sandbox.strike_tester import StrikeTester, OptionChainSimulator, MockTWS, IBKRConnector
from utils.logging_utils import setup_logger
from config.settings import BASE_DIR

# Set up logger
logger = setup_logger("sandbox_gui")

class OptionStrategySandboxGUI:
    """
    GUI for testing option strategies and visualizing results
    """
    def __init__(self, root):
        """
        Initialize the GUI
        
        Args:
            root: Tkinter root window
        """
        self.root = root
        self.root.title("SPX Option Strategy Sandbox")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
        
        # Try to connect to IBKR for real data
        self.ibkr = IBKRConnector()
        connected = self.ibkr.connect_to_tws()
        
        # Initialize option chain simulator as backup
        self.simulator = OptionChainSimulator()
        
        # Create tester using real data if connected, otherwise use simulator
        if connected:
            logger.info("Connected to IBKR - using real market data")
            self.tester = StrikeTester(self.simulator, self.ibkr)
            self.using_real_data = True
        else:
            logger.warning("Could not connect to IBKR - using simulated data")
            self.tester = StrikeTester(self.simulator)
            self.using_real_data = False
        
        # Create GUI elements
        self._create_menu()
        self._create_layout()
        self._create_strategy_settings()
        self._create_market_settings()
        self._create_results_display()
        self._create_chart_area()
        
        # Add data source indicator
        self._create_data_source_indicator()
        
        # Initialize with default values
        self._initialize_defaults()
        
        # Set up event bindings
        self._setup_bindings()
        
        # Start price updates
        self._start_price_updates()
        
        logger.info("Option Strategy Sandbox GUI initialized")
    
    def _create_menu(self):
        """Create the menu bar"""
        self.menu_bar = tk.Menu(self.root)
        
        # File menu
        self.file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.file_menu.add_command(label="Save Results", command=self._save_results)
        self.file_menu.add_command(label="Load Parameters", command=self._load_parameters)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.root.quit)
        self.menu_bar.add_cascade(label="File", menu=self.file_menu)
        
        # Strategy menu
        self.strategy_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.strategy_menu.add_command(label="Iron Condor", command=lambda: self._set_strategy("iron_condor"))
        self.strategy_menu.add_command(label="Double Calendar", command=lambda: self._set_strategy("double_calendar"))
        self.strategy_menu.add_command(label="Put Butterfly", command=lambda: self._set_strategy("put_butterfly"))
        self.menu_bar.add_cascade(label="Strategy", menu=self.strategy_menu)
        
        # Help menu
        self.help_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.help_menu.add_command(label="About", command=self._show_about)
        self.menu_bar.add_cascade(label="Help", menu=self.help_menu)
        
        self.root.config(menu=self.menu_bar)
    
    def _create_layout(self):
        """Create the main layout"""
        # Main frame
        self.main_frame = ttk.Frame(self.root, padding=10)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Left panel for settings
        self.left_panel = ttk.Frame(self.main_frame, width=300)
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # Right panel for results and charts
        self.right_panel = ttk.Frame(self.main_frame)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Status bar
        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def _create_strategy_settings(self):
        """Create strategy settings panel"""
        # Strategy frame
        self.strategy_frame = ttk.LabelFrame(self.left_panel, text="Strategy Settings", padding=10)
        self.strategy_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Strategy type
        ttk.Label(self.strategy_frame, text="Strategy Type:").grid(column=0, row=0, sticky=tk.W, pady=5)
        self.strategy_var = tk.StringVar()
        self.strategy_combo = ttk.Combobox(self.strategy_frame, textvariable=self.strategy_var)
        self.strategy_combo['values'] = ('Iron Condor', 'Double Calendar', 'Put Butterfly')
        self.strategy_combo.grid(column=1, row=0, sticky=tk.W, pady=5)
        self.strategy_combo.state(['readonly'])
        
        # DTE
        ttk.Label(self.strategy_frame, text="Days to Expiration:").grid(column=0, row=1, sticky=tk.W, pady=5)
        self.dte_var = tk.IntVar()
        self.dte_spinbox = ttk.Spinbox(self.strategy_frame, from_=1, to=60, textvariable=self.dte_var, width=5)
        self.dte_spinbox.grid(column=1, row=1, sticky=tk.W, pady=5)
        
        # Iron Condor specific settings
        self.ic_frame = ttk.Frame(self.strategy_frame)
        
        ttk.Label(self.ic_frame, text="Put Delta:").grid(column=0, row=0, sticky=tk.W, pady=5)
        self.put_delta_var = tk.DoubleVar()
        self.put_delta_spinbox = ttk.Spinbox(self.ic_frame, from_=0.1, to=0.5, increment=0.01, 
                                          textvariable=self.put_delta_var, width=5)
        self.put_delta_spinbox.grid(column=1, row=0, sticky=tk.W, pady=5)
        
        ttk.Label(self.ic_frame, text="Call Delta:").grid(column=0, row=1, sticky=tk.W, pady=5)
        self.call_delta_var = tk.DoubleVar()
        self.call_delta_spinbox = ttk.Spinbox(self.ic_frame, from_=0.1, to=0.5, increment=0.01, 
                                           textvariable=self.call_delta_var, width=5)
        self.call_delta_spinbox.grid(column=1, row=1, sticky=tk.W, pady=5)
        
        ttk.Label(self.ic_frame, text="Wing Width:").grid(column=0, row=2, sticky=tk.W, pady=5)
        self.wing_width_var = tk.IntVar()
        self.wing_width_spinbox = ttk.Spinbox(self.ic_frame, from_=5, to=50, increment=5, 
                                           textvariable=self.wing_width_var, width=5)
        self.wing_width_spinbox.grid(column=1, row=2, sticky=tk.W, pady=5)
        
        # Double Calendar specific settings
        self.dc_frame = ttk.Frame(self.strategy_frame)
        
        ttk.Label(self.dc_frame, text="Short DTE:").grid(column=0, row=0, sticky=tk.W, pady=5)
        self.short_dte_var = tk.IntVar()
        self.short_dte_spinbox = ttk.Spinbox(self.dc_frame, from_=1, to=30, textvariable=self.short_dte_var, width=5)
        self.short_dte_spinbox.grid(column=1, row=0, sticky=tk.W, pady=5)
        
        ttk.Label(self.dc_frame, text="Long DTE:").grid(column=0, row=1, sticky=tk.W, pady=5)
        self.long_dte_var = tk.IntVar()
        self.long_dte_spinbox = ttk.Spinbox(self.dc_frame, from_=7, to=60, textvariable=self.long_dte_var, width=5)
        self.long_dte_spinbox.grid(column=1, row=1, sticky=tk.W, pady=5)
        
        ttk.Label(self.dc_frame, text="Delta:").grid(column=0, row=2, sticky=tk.W, pady=5)
        self.dc_delta_var = tk.DoubleVar()
        self.dc_delta_spinbox = ttk.Spinbox(self.dc_frame, from_=0.2, to=0.5, increment=0.01, 
                                          textvariable=self.dc_delta_var, width=5)
        self.dc_delta_spinbox.grid(column=1, row=2, sticky=tk.W, pady=5)
        
        # Put Butterfly specific settings
        self.pb_frame = ttk.Frame(self.strategy_frame)
        
        ttk.Label(self.pb_frame, text="Center Delta:").grid(column=0, row=0, sticky=tk.W, pady=5)
        self.center_delta_var = tk.DoubleVar()
        self.center_delta_spinbox = ttk.Spinbox(self.pb_frame, from_=0.2, to=0.5, increment=0.01, 
                                             textvariable=self.center_delta_var, width=5)
        self.center_delta_spinbox.grid(column=1, row=0, sticky=tk.W, pady=5)
        
        ttk.Label(self.pb_frame, text="Wing Width:").grid(column=0, row=1, sticky=tk.W, pady=5)
        self.pb_wing_width_var = tk.IntVar()
        self.pb_wing_width_spinbox = ttk.Spinbox(self.pb_frame, from_=5, to=50, increment=5, 
                                              textvariable=self.pb_wing_width_var, width=5)
        self.pb_wing_width_spinbox.grid(column=1, row=1, sticky=tk.W, pady=5)
        
        # Add run button
        self.run_button = ttk.Button(self.strategy_frame, text="Run Test", command=self._run_test)
        self.run_button.grid(column=0, row=10, columnspan=2, pady=10)
    
    def _create_market_settings(self):
        """Create market settings panel"""
        # Market frame
        self.market_frame = ttk.LabelFrame(self.left_panel, text="Market Settings", padding=10)
        self.market_frame.pack(fill=tk.X, pady=(0, 10))
        
        # SPX Price
        ttk.Label(self.market_frame, text="SPX Price:").grid(column=0, row=0, sticky=tk.W, pady=5)
        self.spx_price_var = tk.DoubleVar()
        self.spx_price_entry = ttk.Entry(self.market_frame, textvariable=self.spx_price_var, width=10)
        self.spx_price_entry.grid(column=1, row=0, sticky=tk.W, pady=5)
        
        # Volatility
        ttk.Label(self.market_frame, text="Volatility (%):").grid(column=0, row=1, sticky=tk.W, pady=5)
        self.volatility_var = tk.DoubleVar()
        self.volatility_scale = ttk.Scale(self.market_frame, from_=10, to=50, orient=tk.HORIZONTAL,
                                       variable=self.volatility_var, length=150)
        self.volatility_scale.grid(column=1, row=1, sticky=tk.W, pady=5)
        self.volatility_label = ttk.Label(self.market_frame, text="")
        self.volatility_label.grid(column=2, row=1, sticky=tk.W, pady=5)
        
        # Update market settings button
        self.update_market_button = ttk.Button(self.market_frame, text="Update", command=self._update_market_settings)
        self.update_market_button.grid(column=0, row=2, columnspan=2, pady=10)
    
    def _create_results_display(self):
        """Create results display area"""
        results_frame = ttk.LabelFrame(self.right_panel, text="Strategy Results")
        results_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Strategy status label
        self.strategy_status_var = tk.StringVar(value="Ready to run test")
        status_label = ttk.Label(results_frame, textvariable=self.strategy_status_var, font=("Arial", 10))
        status_label.pack(anchor=tk.W, padx=10, pady=5)
        
        # Results table
        results_table_frame = ttk.Frame(results_frame)
        results_table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Create scrolled frame
        self.results_canvas = tk.Canvas(results_table_frame)
        scrollbar = ttk.Scrollbar(results_table_frame, orient="vertical", command=self.results_canvas.yview)
        self.scrollable_results_frame = ttk.Frame(self.results_canvas)
        
        self.scrollable_results_frame.bind(
            "<Configure>",
            lambda e: self.results_canvas.configure(scrollregion=self.results_canvas.bbox("all"))
        )
        
        self.results_canvas.create_window((0, 0), window=self.scrollable_results_frame, anchor="nw")
        self.results_canvas.configure(yscrollcommand=scrollbar.set)
        
        self.results_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Results variables for table
        self.results_vars = {
            "strikes": {},
            "prices": {},
            "greeks": {},
            "metrics": {}
        }
    
    def _create_chart_area(self):
        """Create chart area for P&L visualization"""
        # Chart frame
        self.chart_frame = ttk.LabelFrame(self.right_panel, text="P&L Chart", padding=10)
        self.chart_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create matplotlib figure
        self.figure = plt.Figure(figsize=(8, 4), dpi=100)
        self.ax = self.figure.add_subplot(111)
        
        # Add canvas to frame
        self.canvas = FigureCanvasTkAgg(self.figure, self.chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Initialize chart
        self._initialize_chart()
    
    def _create_data_source_indicator(self):
        """Create an indicator showing if we're using real or simulated data"""
        data_frame = ttk.Frame(self.root)
        data_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        
        data_source = "REAL MARKET DATA" if self.using_real_data else "SIMULATED DATA"
        data_color = "green" if self.using_real_data else "orange"
        
        data_label = ttk.Label(
            data_frame, 
            text=f"Using: {data_source}",
            foreground=data_color,
            font=("Arial", 10, "bold")
        )
        data_label.pack(side=tk.RIGHT)
    
    def _initialize_chart(self):
        """Initialize the P&L chart"""
        # Clear previous plot
        self.ax.clear()
        
        # Set labels
        self.ax.set_title("Strategy P&L at Expiration")
        self.ax.set_xlabel("SPX Price")
        self.ax.set_ylabel("P&L ($)")
        
        # Add grid
        self.ax.grid(True)
        
        # Update canvas
        self.canvas.draw()
    
    def _initialize_defaults(self):
        """Initialize default values"""
        # Market settings
        self.spx_price_var.set(4500.0)
        self.volatility_var.set(20.0)
        self._update_volatility_label()
        
        # Strategy settings
        self.strategy_var.set("Iron Condor")
        self.dte_var.set(1)
        
        # Iron Condor defaults
        self.put_delta_var.set(0.16)
        self.call_delta_var.set(0.16)
        self.wing_width_var.set(20)
        
        # Double Calendar defaults
        self.short_dte_var.set(1)
        self.long_dte_var.set(8)
        self.dc_delta_var.set(0.30)
        
        # Put Butterfly defaults
        self.center_delta_var.set(0.30)
        self.pb_wing_width_var.set(20)
        
        # Show the appropriate strategy frame
        self._show_strategy_frame()
    
    def _setup_bindings(self):
        """Set up event bindings"""
        # Strategy combobox change
        self.strategy_combo.bind("<<ComboboxSelected>>", lambda e: self._show_strategy_frame())
        
        # Volatility scale change
        self.volatility_scale.bind("<Motion>", lambda e: self._update_volatility_label())
        
        # Update volatility label on value change
        self.volatility_var.trace_add("write", lambda *args: self._update_volatility_label())
    
    def _update_volatility_label(self):
        """Update the volatility label with current value"""
        self.volatility_label.config(text=f"{self.volatility_var.get():.1f}%")
    
    def _show_strategy_frame(self):
        """Show the appropriate strategy frame based on selection"""
        # Hide all strategy frames
        for frame in [self.ic_frame, self.dc_frame, self.pb_frame]:
            for widget in frame.winfo_children():
                widget.grid_forget()
            frame.grid_forget()
        
        # Show the selected strategy frame
        strategy = self.strategy_var.get()
        
        if strategy == "Iron Condor":
            self.ic_frame.grid(column=0, row=3, columnspan=2, sticky=tk.W, pady=5)
            for widget in self.ic_frame.winfo_children():
                widget.grid_configure()
        
        elif strategy == "Double Calendar":
            self.dc_frame.grid(column=0, row=3, columnspan=2, sticky=tk.W, pady=5)
            for widget in self.dc_frame.winfo_children():
                widget.grid_configure()
        
        elif strategy == "Put Butterfly":
            self.pb_frame.grid(column=0, row=3, columnspan=2, sticky=tk.W, pady=5)
            for widget in self.pb_frame.winfo_children():
                widget.grid_configure()
    
    def _update_market_settings(self):
        """Update market settings in the simulator"""
        try:
            # Get values
            spx_price = float(self.spx_price_var.get())
            volatility = float(self.volatility_var.get()) / 100.0  # Convert percentage to decimal
            
            # Update simulator
            self.simulator.set_underlying_price(spx_price)
            self.simulator.set_volatility(volatility)
            
            # Update status
            self.status_bar.config(text=f"Market settings updated: SPX={spx_price}, IV={volatility*100:.1f}%")
            logger.info(f"Market settings updated: SPX={spx_price}, IV={volatility*100:.1f}%")
            
            # Run test with new settings if results already exist
            if hasattr(self, 'last_test_result') and self.last_test_result:
                self._run_test()
        
        except ValueError as e:
            self.status_bar.config(text=f"Error: {str(e)}")
            logger.error(f"Error updating market settings: {str(e)}")
    
    def _run_test(self):
        """Run the strategy test with current settings"""
        # Get current strategy and settings
        strategy = self.strategy_var.get()
        dte = int(self.dte_var.get())
        
        # Update UI to show test is running
        if self.using_real_data:
            self.strategy_status_var.set(f"Running {strategy} test with real market data...")
        else:
            self.strategy_status_var.set(f"Running {strategy} test with simulated data...")
        self.root.update()
        
        # Create data dictionary to store results
        self.results_data = {}
        
        try:
            # Run the appropriate test based on strategy
            if strategy == "Iron Condor":
                # Get iron condor parameters
                short_delta = float(self.put_delta_var.get())
                wing_width = float(self.wing_width_var.get())
                
                # Run the test
                self.results_data = self.tester.test_iron_condor(dte, short_delta, wing_width)
            
            elif strategy == "Double Calendar":
                # Get double calendar parameters
                front_dte = int(self.short_dte_var.get())
                back_dte = dte
                short_delta = float(self.dc_delta_var.get())
                
                # Run the test
                self.results_data = self.tester.test_double_calendar(front_dte, back_dte, short_delta)
            
            elif strategy == "Put Butterfly":
                # Get butterfly parameters
                short_delta = float(self.center_delta_var.get())
                wing_width = float(self.pb_wing_width_var.get())
                
                # Run the test
                self.results_data = self.tester.test_put_butterfly(dte, short_delta, wing_width)
            
            # Update results display
            self._update_results_display()
            
            # Update status
            self.strategy_status_var.set(f"{strategy} test completed successfully")
        
        except Exception as ex:
            # Log the error
            logger.error(f"Error running test: {str(ex)}")
            
            # Update status
            self.strategy_status_var.set(f"Error: {str(ex)}")
            
            # Update status bar - fix the lambda function to avoid referencing 'e'
            error_msg = str(ex)  # Store the error message
            self.root.after(0, lambda: self.status_bar.config(text=f"Error: {error_msg}"))
    
    def _update_results_display(self):
        """Update results display with current test results"""
        # Clear previous results
        for widget in self.scrollable_results_frame.winfo_children():
            widget.destroy()
        
        if not self.results_data:
            return
        
        # Check for error
        if "error" in self.results_data:
            error_label = ttk.Label(
                self.scrollable_results_frame,
                text=f"Error: {self.results_data['error']}",
                foreground="red",
                font=("Arial", 10, "bold")
            )
            error_label.pack(anchor=tk.W, padx=10, pady=5)
            return
        
        # Strategy info
        strategy_name = self.results_data.get("strategy", "Unknown Strategy")
        dte = self.results_data.get("dte", 0)
        
        strategy_info = ttk.Label(
            self.scrollable_results_frame,
            text=f"{strategy_name} with {dte} DTE",
            font=("Arial", 12, "bold")
        )
        strategy_info.pack(anchor=tk.W, padx=10, pady=(10, 5))
        
        # Create frames for different sections
        strikes_frame = ttk.LabelFrame(self.scrollable_results_frame, text="Selected Strikes")
        strikes_frame.pack(fill=tk.X, padx=10, pady=5)
        
        prices_frame = ttk.LabelFrame(self.scrollable_results_frame, text="Option Prices")
        prices_frame.pack(fill=tk.X, padx=10, pady=5)
        
        greeks_frame = ttk.LabelFrame(self.scrollable_results_frame, text="Greeks")
        greeks_frame.pack(fill=tk.X, padx=10, pady=5)
        
        metrics_frame = ttk.LabelFrame(self.scrollable_results_frame, text="Strategy Metrics")
        metrics_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Add strike information
        row = 0
        for label, value in self.results_data.get("strikes", {}).items():
            strike_label = ttk.Label(strikes_frame, text=f"{label.replace('_', ' ').title()}:")
            strike_label.grid(row=row, column=0, sticky=tk.W, padx=10, pady=2)
            
            strike_value = ttk.Label(strikes_frame, text=f"{value:.2f}")
            strike_value.grid(row=row, column=1, sticky=tk.W, padx=10, pady=2)
            row += 1
        
        # Add price information
        row = 0
        for label, value in self.results_data.get("prices", {}).items():
            price_label = ttk.Label(prices_frame, text=f"{label.replace('_', ' ').title()}:")
            price_label.grid(row=row, column=0, sticky=tk.W, padx=10, pady=2)
            
            price_value = ttk.Label(prices_frame, text=f"${value:.2f}")
            price_value.grid(row=row, column=1, sticky=tk.W, padx=10, pady=2)
            row += 1
        
        # Add greek information
        row = 0
        for label, value in self.results_data.get("greeks", {}).items():
            greek_label = ttk.Label(greeks_frame, text=f"{label.replace('_', ' ').title()}:")
            greek_label.grid(row=row, column=0, sticky=tk.W, padx=10, pady=2)
            
            greek_value = ttk.Label(greeks_frame, text=f"{value:.3f}")
            greek_value.grid(row=row, column=1, sticky=tk.W, padx=10, pady=2)
            row += 1
        
        # Add metrics information
        row = 0
        for label, value in self.results_data.get("metrics", {}).items():
            metric_label = ttk.Label(metrics_frame, text=f"{label.replace('_', ' ').title()}:")
            metric_label.grid(row=row, column=0, sticky=tk.W, padx=10, pady=2)
            
            if label in ["risk_reward"]:
                metric_value = ttk.Label(metrics_frame, text=f"{value:.3f}")
            else:
                metric_value = ttk.Label(metrics_frame, text=f"${value:.2f}")
            
            metric_value.grid(row=row, column=1, sticky=tk.W, padx=10, pady=2)
            row += 1
    
    def _update_chart(self, result):
        """Update the P&L chart with test results"""
        # Clear previous plot
        self.ax.clear()
        
        # Get current SPX price
        current_price = self.simulator.underlying_price
        
        # Create range of prices for P&L calculation
        price_range = np.linspace(current_price * 0.9, current_price * 1.1, 100)
        
        # Calculate P&L at expiration for the price range
        pnl = self._calculate_pnl_at_expiration(result, price_range)
        
        # Plot P&L
        self.ax.plot(price_range, pnl, 'b-')
        
        # Add horizontal line at zero
        self.ax.axhline(y=0, color='r', linestyle='-')
        
        # Add vertical line at current price
        self.ax.axvline(x=current_price, color='g', linestyle='--')
        
        # Set labels
        strategy = self.strategy_var.get()
        self.ax.set_title(f"{strategy} P&L at Expiration")
        self.ax.set_xlabel("SPX Price")
        self.ax.set_ylabel("P&L ($)")
        
        # Add grid
        self.ax.grid(True)
        
        # Update canvas
        self.canvas.draw()
    
    def _calculate_pnl_at_expiration(self, result, price_range):
        """
        Calculate P&L at expiration for a range of prices
        
        Args:
            result: Test result dictionary
            price_range: Array of prices
            
        Returns:
            np.array: P&L values
        """
        strategy = self.strategy_var.get()
        options = result.get('options', {})
        
        if strategy == "Iron Condor":
            # Extract strikes
            short_put = options.get('short_put')
            long_put = options.get('long_put')
            short_call = options.get('short_call')
            long_call = options.get('long_call')
            
            if not all([short_put, long_put, short_call, long_call]):
                return np.zeros_like(price_range)
            
            # Calculate net credit
            net_credit = (
                short_put.mid_price - long_put.mid_price + 
                short_call.mid_price - long_call.mid_price
            )
            
            # Initialize P&L array
            pnl = np.ones_like(price_range) * net_credit * 100
            
            # Adjust P&L for each price point
            for i, price in enumerate(price_range):
                # Long put payoff
                if price < long_put.strike:
                    pnl[i] += (long_put.strike - price) * 100
                
                # Short put payoff
                if price < short_put.strike:
                    pnl[i] -= (short_put.strike - price) * 100
                
                # Short call payoff
                if price > short_call.strike:
                    pnl[i] -= (price - short_call.strike) * 100
                
                # Long call payoff
                if price > long_call.strike:
                    pnl[i] += (price - long_call.strike) * 100
        
        elif strategy == "Double Calendar":
            # For double calendar, we need a different approach since it's not a pure expiration play
            # Here we'll use the metrics from the tester
            max_profit = result.get('risk_reward', {}).get('max_profit', 0)
            max_loss = result.get('risk_reward', {}).get('max_loss', 0)
            
            # Create a simple bell curve for the P&L
            pnl = np.zeros_like(price_range)
            center_price = self.simulator.underlying_price
            width = center_price * 0.05  # 5% width
            
            for i, price in enumerate(price_range):
                # Simple bell curve approximation
                distance = abs(price - center_price)
                if distance < width:
                    pnl[i] = max_profit * (1 - (distance / width) ** 2)
                else:
                    pnl[i] = -max_loss
        
        elif strategy == "Put Butterfly":
            # Extract strikes
            lower_put = options.get('lower_put')
            center_put = options.get('center_put')
            upper_put = options.get('upper_put')
            
            if not all([lower_put, center_put, upper_put]):
                return np.zeros_like(price_range)
            
            # Calculate net debit
            net_debit = lower_put.mid_price - 2 * center_put.mid_price + upper_put.mid_price
            
            # Initialize P&L array
            pnl = np.ones_like(price_range) * -net_debit * 100
            
            # Adjust P&L for each price point
            for i, price in enumerate(price_range):
                # Lower put payoff
                if price < lower_put.strike:
                    pnl[i] += (lower_put.strike - price) * 100
                
                # Center put payoff (short 2 contracts)
                if price < center_put.strike:
                    pnl[i] -= 2 * (center_put.strike - price) * 100
                
                # Upper put payoff
                if price < upper_put.strike:
                    pnl[i] += (upper_put.strike - price) * 100
        
        else:
            return np.zeros_like(price_range)
        
        return pnl
    
    def _clear_results(self):
        """Clear all results displays"""
        # Clear trees
        for tree in [self.strikes_tree, self.metrics_tree, self.greeks_tree]:
            for item in tree.get_children():
                tree.delete(item)
        
        # Clear chart
        self._initialize_chart()
    
    def _save_results(self):
        """Save the current results to a file"""
        if not hasattr(self, 'last_test_result') or not self.last_test_result:
            self.status_bar.config(text="No results to save")
            return
        
        try:
            # Create results directory if it doesn't exist
            results_dir = os.path.join(BASE_DIR, "results")
            os.makedirs(results_dir, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            strategy = self.strategy_var.get().lower().replace(" ", "_")
            filename = f"{strategy}_{timestamp}.json"
            filepath = os.path.join(results_dir, filename)
            
            # Save the results
            with open(filepath, 'w') as f:
                json.dump(self._prepare_results_for_saving(), f, indent=2)
            
            self.status_bar.config(text=f"Results saved to {filepath}")
            logger.info(f"Results saved to {filepath}")
        
        except Exception as e:
            self.status_bar.config(text=f"Error saving results: {str(e)}")
            logger.error(f"Error saving results: {str(e)}")
    
    def _prepare_results_for_saving(self):
        """Prepare results for saving to JSON"""
        # Convert complex objects to simple dictionaries
        results = {}
        results['strategy'] = self.strategy_var.get()
        results['market'] = {
            'spx_price': self.spx_price_var.get(),
            'volatility': self.volatility_var.get() / 100.0
        }
        results['parameters'] = {}
        
        # Add strategy-specific parameters
        if results['strategy'] == "Iron Condor":
            results['parameters'] = {
                'dte': self.dte_var.get(),
                'put_delta': self.put_delta_var.get(),
                'call_delta': self.call_delta_var.get(),
                'wing_width': self.wing_width_var.get()
            }
        elif results['strategy'] == "Double Calendar":
            results['parameters'] = {
                'short_dte': self.short_dte_var.get(),
                'long_dte': self.long_dte_var.get(),
                'put_delta': self.dc_delta_var.get(),
                'call_delta': self.dc_delta_var.get()
            }
        elif results['strategy'] == "Put Butterfly":
            results['parameters'] = {
                'dte': self.dte_var.get(),
                'center_delta': self.center_delta_var.get(),
                'wing_width': self.pb_wing_width_var.get()
            }
        
        # Add strikes
        strikes = {}
        for k, v in self.last_test_result.get('strikes', {}).items():
            strikes[k] = v
        results['strikes'] = strikes
        
        # Add risk metrics
        results['risk_metrics'] = self.last_test_result.get('risk_reward', {})
        
        # Add greeks
        results['greeks'] = self.last_test_result.get('greeks', {})
        
        # Add timestamp
        results['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return results
    
    def _load_parameters(self):
        """Load parameters from a saved results file"""
        # This would be implemented to load back saved configurations
        self.status_bar.config(text="Load parameters not implemented yet")
    
    def _set_strategy(self, strategy):
        """Set the strategy from the menu"""
        if strategy == "iron_condor":
            self.strategy_var.set("Iron Condor")
        elif strategy == "double_calendar":
            self.strategy_var.set("Double Calendar")
        elif strategy == "put_butterfly":
            self.strategy_var.set("Put Butterfly")
        
        self._show_strategy_frame()
    
    def _show_about(self):
        """Show about dialog"""
        about_window = tk.Toplevel(self.root)
        about_window.title("About SPX Option Strategy Sandbox")
        about_window.geometry("400x300")
        about_window.resizable(False, False)
        
        # Add some padding
        frame = ttk.Frame(about_window, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(frame, text="SPX Option Strategy Sandbox", font=("Arial", 14, "bold")).pack(pady=(0, 10))
        
        # Version
        ttk.Label(frame, text="Version 1.0").pack(pady=(0, 20))
        
        # Description
        description = (
            "This application allows you to test different option strategies "
            "with simulated option chains. You can adjust market conditions "
            "and strategy parameters to see how they affect the risk/reward profile."
        )
        desc_label = ttk.Label(frame, text=description, wraplength=360, justify=tk.CENTER)
        desc_label.pack(pady=(0, 20))
        
        # Copyright
        ttk.Label(frame, text="© 2023").pack(pady=(0, 10))
        
        # Close button
        ttk.Button(frame, text="Close", command=about_window.destroy).pack()

    def _start_price_updates(self):
        """Start background thread to update market data"""
        def update_loop():
            while self.running:
                try:
                    if self.using_real_data:
                        # Get real price from IBKR
                        spx_price = self.ibkr.get_spx_price()
                    else:
                        # Use simulated price
                        spx_price = self.simulator.underlying_price
                        # Add some random movement to simulated price
                        self.simulator.underlying_price += np.random.normal(0, 0.5)
                    
                    # Update GUI with the price if valid
                    if spx_price > 0:
                        self.spx_price_var.set(round(spx_price, 2))
                    
                    # Update status bar
                    now = datetime.now()
                    data_source = "Real Data" if self.using_real_data else "Simulated Data"
                    self.status_bar.config(text=f"SPX: {self.spx_price_var.get()} - {data_source} - Updated: {now.strftime('%H:%M:%S')}")
                    
                except Exception as e:
                    logger.error(f"Error updating price: {str(e)}")
                
                # Update frequency
                time.sleep(2 if self.using_real_data else 1)  
        
        self.running = True
        self.price_update_thread = threading.Thread(target=update_loop, daemon=True)
        self.price_update_thread.start()


if __name__ == "__main__":
    # Create the root window
    root = tk.Tk()
    
    # Create the application
    app = OptionStrategySandboxGUI(root)
    
    # Start the main loop
    root.mainloop()
