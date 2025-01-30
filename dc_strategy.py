from datetime import datetime, timedelta
import pytz
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum

class DCStrategyState(Enum):
    WAITING = "Waiting for entry"
    SEARCHING = "Searching for strikes"
    ENTERING = "Entering position"
    MONITORING = "Monitoring position"
    EXITING = "Exiting position"
    COMPLETED = "Trade completed"
    ERROR = "Error state"

@dataclass
class OrderFill:
    order_id: int
    fill_price: float
    quantity: int
    remaining: int
    contract_type: str  # 'FRONT_PUT', 'BACK_PUT', 'FRONT_CALL', 'BACK_CALL'
    timestamp: datetime

@dataclass
class DCPosition:
    entry_time: datetime
    quantity: int
    front_put_strike: float
    front_call_strike: float
    back_put_strike: float
    back_call_strike: float
    front_expiry: str
    back_expiry: str
    position_delta: float = 0
    current_pnl: float = 0
    entry_price: Optional[float] = None
    fills: Dict[str, OrderFill] = field(default_factory=dict)
    order_ids: Dict[str, int] = field(default_factory=dict)
    closing_order_ids: Dict[str, int] = field(default_factory=dict)
    closing_fills: Dict[str, OrderFill] = field(default_factory=dict)
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    price_attempts: int = 0
    last_price_update: Optional[datetime] = None
    is_manual_control: bool = False
    
    def is_fully_filled(self) -> bool:
        """Check if all entry legs are fully filled"""
        expected_legs = {'FRONT_PUT', 'BACK_PUT', 'FRONT_CALL', 'BACK_CALL'}
        return all(leg in self.fills and self.fills[leg].remaining == 0 for leg in expected_legs)
    
    def is_fully_closed(self) -> bool:
        """Check if all closing orders are fully filled"""
        expected_legs = {'FRONT_PUT', 'BACK_PUT', 'FRONT_CALL', 'BACK_CALL'}
        return all(leg in self.closing_fills and self.closing_fills[leg].remaining == 0 for leg in expected_legs)
    
    def calculate_entry_price(self) -> float:
        """Calculate total entry price once all legs are filled"""
        if not self.is_fully_filled():
            return None
            
        # Short front month, long back month
        put_spread = (self.fills['BACK_PUT'].fill_price - self.fills['FRONT_PUT'].fill_price) * self.quantity * 100
        call_spread = (self.fills['BACK_CALL'].fill_price - self.fills['FRONT_CALL'].fill_price) * self.quantity * 100
        return put_spread + call_spread
        
    def calculate_exit_price(self) -> float:
        """Calculate total exit price once all closing orders are filled"""
        if not self.is_fully_closed():
            return None
            
        # Long front month (buying back shorts), short back month (selling longs)
        put_spread = (self.closing_fills['FRONT_PUT'].fill_price - self.closing_fills['BACK_PUT'].fill_price) * self.quantity * 100
        call_spread = (self.closing_fills['FRONT_CALL'].fill_price - self.closing_fills['BACK_CALL'].fill_price) * self.quantity * 100
        return put_spread + call_spread

class MondayDCStrategy:
    def __init__(self, tws, order_manager):
        self.tws = tws
        self.order_manager = order_manager
        self.et_tz = pytz.timezone('US/Eastern')
        self.state = DCStrategyState.WAITING
        self.current_position: Optional[DCPosition] = None
        self.target_entry_time = None
        self.target_exit_time = None
        self.daily_pnl = 0  # Track daily P&L
        self.max_daily_loss = -50000  # $50K daily loss limit
        
    def is_monday(self) -> bool:
        """Check if today is Monday"""
        return datetime.now(self.et_tz).weekday() == 0
    
    def set_entry_time(self):
        """Set target entry time to Monday 12:00 PM ET"""
        now = datetime.now(self.et_tz)
        self.target_entry_time = now.replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        
        # Set exit time to Thursday 9:45 AM
        days_to_thursday = (3 - now.weekday()) % 7
        self.target_exit_time = (now + timedelta(days=days_to_thursday)).replace(
            hour=9, minute=45, second=0, microsecond=0
        )
    
    def get_expiry_dates(self) -> tuple[str, str]:
        """Get front (3DTE) and back (7DTE) expiry dates"""
        now = datetime.now(self.et_tz)
        front_expiry = now + timedelta(days=3)
        back_expiry = now + timedelta(days=7)
        # Format as YYYYMMDD
        return (
            front_expiry.strftime('%Y%m%d'),
            back_expiry.strftime('%Y%m%d')
        )
    
    def is_valid_trading_day(self) -> bool:
        """Check if today is a valid trading day (has options available)"""
        if not self.tws.spx_price:
            print("Cannot check trading day validity: SPX price not available")
            return False
            
        # Round to nearest 5 to get ATM strike
        atm_strike = round(self.tws.spx_price / 5) * 5
        front_expiry, back_expiry = self.get_expiry_dates()
        
        # Request contract details for both expiries
        front_contract = self.tws.create_spx_option_contract(
            right="C",
            strike=atm_strike,
            expiry=front_expiry
        )
        back_contract = self.tws.create_spx_option_contract(
            right="C",
            strike=atm_strike,
            expiry=back_expiry
        )
        
        try:
            front_details = self.tws.request_contract_details(front_contract)
            back_details = self.tws.request_contract_details(back_contract)
            return bool(front_details and back_details)
        except Exception as e:
            print(f"Error checking trading day validity: {e}")
            return False
            
    def find_strike_prices(self, spx_price: float) -> tuple[float, float, float, float]:
        """
        Find appropriate strikes based on delta requirements
        Returns (front_put_strike, front_call_strike, back_put_strike, back_call_strike)
        """
        front_expiry, back_expiry = self.get_expiry_dates()
        
        # Get strikes within ±5% of current price
        strike_range = spx_price * 0.05
        min_strike = spx_price - strike_range
        max_strike = spx_price + strike_range
        
        # Request option chains for both expiries
        front_puts = self.tws.request_option_chain(
            expiry=front_expiry,
            right="P",
            min_strike=min_strike,
            max_strike=max_strike
        )
        front_calls = self.tws.request_option_chain(
            expiry=front_expiry,
            right="C",
            min_strike=min_strike,
            max_strike=max_strike
        )
        back_puts = self.tws.request_option_chain(
            expiry=back_expiry,
            right="P",
            min_strike=min_strike,
            max_strike=max_strike
        )
        back_calls = self.tws.request_option_chain(
            expiry=back_expiry,
            right="C",
            min_strike=min_strike,
            max_strike=max_strike
        )
        
        # Find strikes with closest deltas to targets
        TARGET_PUT_DELTA = -0.12
        TARGET_CALL_DELTA = 0.17
        DELTA_TOLERANCE = 0.02
        
        def find_closest_delta(options, target_delta):
            closest = None
            min_diff = float('inf')
            for opt in options:
                if opt.delta is None:
                    continue
                diff = abs(opt.delta - target_delta)
                if diff < min_diff:
                    min_diff = diff
                    closest = opt
            return closest.strike if closest else None
            
        front_put_strike = find_closest_delta(front_puts, TARGET_PUT_DELTA)
        front_call_strike = find_closest_delta(front_calls, TARGET_CALL_DELTA)
        back_put_strike = find_closest_delta(back_puts, TARGET_PUT_DELTA)
        back_call_strike = find_closest_delta(back_calls, TARGET_CALL_DELTA)
        
        if not all([front_put_strike, front_call_strike, back_put_strike, back_call_strike]):
            raise ValueError("Could not find suitable strikes for all legs")
            
        return front_put_strike, front_call_strike, back_put_strike, back_call_strike
    
    def calculate_position_delta(self) -> float:
        """Calculate current position delta"""
        if not self.current_position:
            return 0
            
        total_delta = 0
        for pos in self.tws.positions.values():
            if pos.delta is not None:
                total_delta += pos.delta * pos.position
        return total_delta
    
    def calculate_pnl_percentage(self) -> float:
        """Calculate current P&L as percentage of entry premium"""
        if not self.current_position:
            return 0
            
        try:
            # Get current market prices for all legs
            front_put = self.tws.get_option_price(
                strike=self.current_position.front_put_strike,
                expiry=self.current_position.front_expiry,
                right="P"
            )
            back_put = self.tws.get_option_price(
                strike=self.current_position.back_put_strike,
                expiry=self.current_position.back_expiry,
                right="P"
            )
            front_call = self.tws.get_option_price(
                strike=self.current_position.front_call_strike,
                expiry=self.current_position.front_expiry,
                right="C"
            )
            back_call = self.tws.get_option_price(
                strike=self.current_position.back_call_strike,
                expiry=self.current_position.back_expiry,
                right="C"
            )
            
            # Calculate current position value
            # Short front month, long back month
            put_spread_value = (back_put - front_put) * self.current_position.quantity * 100
            call_spread_value = (back_call - front_call) * self.current_position.quantity * 100
            current_value = put_spread_value + call_spread_value
            
            # Calculate P&L percentage
            if self.current_position.entry_price:
                pnl_pct = ((current_value / abs(self.current_position.entry_price)) - 1) * 100
                return pnl_pct
            else:
                print("Entry price not yet set")
                return 0
                
        except Exception as e:
            print(f"Error calculating P&L: {e}")
            return 0
    
    def should_exit(self) -> bool:
        """Check if any exit conditions are met"""
        if not self.current_position:
            return False
            
        now = datetime.now(self.et_tz)
        
        # 1. Time stop
        if now >= self.target_exit_time:
            print("Exit trigger: Time stop reached")
            return True
            
        # 2. Delta threshold
        position_delta = self.calculate_position_delta()
        if abs(position_delta) > 11:
            print(f"Exit trigger: Delta threshold exceeded ({position_delta})")
            return True
            
        # 3. Profit target
        pnl_percentage = self.calculate_pnl_percentage()
        if pnl_percentage >= 45:
            print(f"Exit trigger: Profit target reached ({pnl_percentage}%)")
            return True
            
        return False
    
    def check_daily_loss_limit(self) -> bool:
        """Check if we've hit our daily loss limit"""
        if self.daily_pnl <= self.max_daily_loss:
            print(f"Daily loss limit hit: ${self.daily_pnl}")
            return True
        return False
        
    def create_calendar_bag_order(self, strike: float, front_expiry: str, back_expiry: str, 
                                right: str, quantity: int, is_closing: bool = False) -> int:
        """Create a BAG order for a calendar spread"""
        # Front month leg (short for entry, long for exit)
        front_leg = self.tws.create_spx_option_contract(
            strike=strike,
            expiry=front_expiry,
            right=right
        )
        front_leg.exchange = "CBOE"
        
        # Back month leg (long for entry, short for exit)
        back_leg = self.tws.create_spx_option_contract(
            strike=strike,
            expiry=back_expiry,
            right=right
        )
        back_leg.exchange = "CBOE"
        
        # For closing orders, reverse the signs
        front_qty = quantity if is_closing else -quantity
        back_qty = -quantity if is_closing else quantity
        
        # Create BAG order
        order_id = self.order_manager.create_bag_order(
            legs=[
                (front_leg, front_qty),
                (back_leg, back_qty)
            ],
            order_type="LMT"
        )
        
        return order_id
        
    def handle_price_improvement(self):
        """Handle price improvement logic for unfilled orders"""
        if not self.current_position or not self.current_position.last_price_update:
            return
            
        now = datetime.now(self.et_tz)
        time_since_update = (now - self.current_position.last_price_update).total_seconds()
        
        # Check if 60 seconds have passed since last price update
        if time_since_update >= 60:
            if self.current_position.price_attempts >= 3:
                print("Order not filled after 3 price improvements. Manual intervention required.")
                self.current_position.is_manual_control = True
                # Cancel all pending orders
                order_ids = (self.current_position.order_ids if self.state == DCStrategyState.ENTERING 
                           else self.current_position.closing_order_ids)
                for order_id in order_ids.values():
                    self.order_manager.cancel_order(order_id)
                self.state = DCStrategyState.ERROR
            else:
                # Improve price by one tick
                self.current_position.price_attempts += 1
                order_ids = (self.current_position.order_ids if self.state == DCStrategyState.ENTERING 
                           else self.current_position.closing_order_ids)
                for order_id in order_ids.values():
                    self.order_manager.improve_order_price(order_id, 0.05)  # One tick = $0.05
                self.current_position.last_price_update = now
                print(f"Improving order prices. Attempt {self.current_position.price_attempts}/3")
                
    def enter_position(self, spx_price: float):
        """Enter the DC position using BAG orders"""
        if self.state != DCStrategyState.SEARCHING:
            return
            
        try:
            front_expiry, back_expiry = self.get_expiry_dates()
            front_put, front_call, back_put, back_call = self.find_strike_prices(spx_price)
            
            # Create position object
            self.current_position = DCPosition(
                entry_time=datetime.now(self.et_tz),
                quantity=6,
                front_put_strike=front_put,
                front_call_strike=front_call,
                back_put_strike=back_put,
                back_call_strike=back_call,
                front_expiry=front_expiry,
                back_expiry=back_expiry,
                last_price_update=datetime.now(self.et_tz)
            )
            
            # Create BAG orders for put and call calendars
            put_order_id = self.create_calendar_bag_order(
                strike=front_put,
                front_expiry=front_expiry,
                back_expiry=back_expiry,
                right="P",
                quantity=6
            )
            self.current_position.order_ids['PUT_CALENDAR'] = put_order_id
            
            call_order_id = self.create_calendar_bag_order(
                strike=front_call,
                front_expiry=front_expiry,
                back_expiry=back_expiry,
                right="C",
                quantity=6
            )
            self.current_position.order_ids['CALL_CALENDAR'] = call_order_id
            
            # Submit orders
            for order_id in self.current_position.order_ids.values():
                self.order_manager.submit_order(order_id)
            
            self.state = DCStrategyState.ENTERING
            print(f"Entering position with BAG orders - Order IDs: {self.current_position.order_ids}")
            
        except Exception as e:
            print(f"Error entering position: {e}")
            self.state = DCStrategyState.ERROR
    
    def exit_position(self):
        """Exit the entire position using BAG orders"""
        if not self.current_position or self.state != DCStrategyState.EXITING:
            return
            
        try:
            # Reset price improvement tracking for exit orders
            self.current_position.price_attempts = 0
            self.current_position.last_price_update = datetime.now(self.et_tz)
            
            # Create BAG orders for put and call calendar exits
            # Note: For exits, we reverse the quantities
            put_close_id = self.create_calendar_bag_order(
                strike=self.current_position.front_put_strike,
                front_expiry=self.current_position.front_expiry,
                back_expiry=self.current_position.back_expiry,
                right="P",
                quantity=6,
                is_closing=True  # This will reverse the signs of the quantities
            )
            self.current_position.closing_order_ids['PUT_CALENDAR'] = put_close_id
            
            call_close_id = self.create_calendar_bag_order(
                strike=self.current_position.front_call_strike,
                front_expiry=self.current_position.front_expiry,
                back_expiry=self.current_position.back_expiry,
                right="C",
                quantity=6,
                is_closing=True
            )
            self.current_position.closing_order_ids['CALL_CALENDAR'] = call_close_id
            
            # Submit orders
            for order_id in self.current_position.closing_order_ids.values():
                self.order_manager.submit_order(order_id)
            
            print(f"Exiting position with BAG orders - Closing Order IDs: {self.current_position.closing_order_ids}")
            
        except Exception as e:
            print(f"Error exiting position: {e}")
            # Stay in EXITING state to retry
    
    def update(self):
        """Main update loop - called periodically"""
        now = datetime.now(self.et_tz)
        
        # Check daily loss limit first
        if self.check_daily_loss_limit():
            if self.current_position and self.state != DCStrategyState.COMPLETED:
                print("Daily loss limit hit - Exiting all positions")
                self.state = DCStrategyState.EXITING
                self.exit_position()
            return
            
        if self.state == DCStrategyState.WAITING:
            if self.is_monday() and self.is_valid_trading_day() and now.time() >= self.target_entry_time.time():
                self.state = DCStrategyState.SEARCHING
                
        elif self.state == DCStrategyState.SEARCHING:
            if self.tws.spx_price:
                self.enter_position(self.tws.spx_price)
                
        elif self.state == DCStrategyState.ENTERING:
            if not self.current_position.is_manual_control:
                self.handle_price_improvement()
                
        elif self.state == DCStrategyState.MONITORING:
            if self.should_exit():
                self.state = DCStrategyState.EXITING
                self.exit_position()
                
        # Update position metrics
        if self.current_position:
            self.current_position.position_delta = self.calculate_position_delta()
            self.current_position.current_pnl = self.calculate_pnl_percentage()
            # Update daily P&L
            if self.current_position.entry_price:
                self.daily_pnl = self.calculate_pnl_percentage() * abs(self.current_position.entry_price) / 100
    
    def on_order_fill(self, order_id: int, fill_price: float, quantity: int, remaining: int):
        """Handle order fills for both entry and exit orders"""
        if not self.current_position:
            return
        
        # Check if this is an entry or exit order
        leg_type = None
        is_closing_order = False
        
        # Check entry orders
        if self.state == DCStrategyState.ENTERING:
            for leg, leg_order_id in self.current_position.order_ids.items():
                if leg_order_id == order_id:
                    leg_type = leg
                    break
                
            if leg_type:
                # Record the entry fill
                self.current_position.fills[leg_type] = OrderFill(
                    order_id=order_id,
                    fill_price=fill_price,
                    quantity=quantity,
                    remaining=remaining,
                    contract_type=leg_type,
                    timestamp=datetime.now(self.et_tz)
                )
                
                # Check if position is fully filled
                if self.current_position.is_fully_filled():
                    self.current_position.entry_price = self.current_position.calculate_entry_price()
                    print(f"Position fully filled. Entry price: {self.current_position.entry_price}")
                    self.state = DCStrategyState.MONITORING
                else:
                    filled_legs = [leg for leg, fill in self.current_position.fills.items() if fill.remaining == 0]
                    print(f"Partial entry fill - Complete legs: {filled_legs}")
                
        # Check exit orders
        elif self.state == DCStrategyState.EXITING:
            for leg, leg_order_id in self.current_position.closing_order_ids.items():
                if leg_order_id == order_id:
                    leg_type = leg
                    is_closing_order = True
                    break
                
            if leg_type:
                # Record the exit fill
                self.current_position.closing_fills[leg_type] = OrderFill(
                    order_id=order_id,
                    fill_price=fill_price,
                    quantity=quantity,
                    remaining=remaining,
                    contract_type=leg_type,
                    timestamp=datetime.now(self.et_tz)
                )
                
                # Check if position is fully closed
                if self.current_position.is_fully_closed():
                    self.current_position.exit_price = self.current_position.calculate_exit_price()
                    self.current_position.exit_time = datetime.now(self.et_tz)
                    print(f"Position fully closed. Exit price: {self.current_position.exit_price}")
                    self.state = DCStrategyState.COMPLETED
                else:
                    closed_legs = [leg for leg, fill in self.current_position.closing_fills.items() if fill.remaining == 0]
                    print(f"Partial exit fill - Complete legs: {closed_legs}")
        
        if not leg_type:
            print(f"Received fill for unknown order ID: {order_id}") 