from ibapi.order import Order
from ibapi.contract import Contract
from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum
import uuid
from datetime import datetime

class OrderStatus(Enum):
    CREATED = "Created"
    SUBMITTED = "Submitted"
    ACKNOWLEDGED = "Acknowledged"
    PENDING_SUBMIT = "PendingSubmit"
    PENDING_CANCEL = "PendingCancel"
    PRESUBMITTED = "PreSubmitted"
    CANCELLED = "Cancelled"
    FILLED = "Filled"
    PARTIALLY_FILLED = "PartiallyFilled"
    ERROR = "Error"
    
    @classmethod
    def from_tws_status(cls, status: str) -> 'OrderStatus':
        status_map = {
            "PendingSubmit": cls.PENDING_SUBMIT,
            "PendingCancel": cls.PENDING_CANCEL,
            "PreSubmitted": cls.PRESUBMITTED,
            "Submitted": cls.SUBMITTED,
            "Cancelled": cls.CANCELLED,
            "Filled": cls.FILLED,
            "PartiallyFilled": cls.PARTIALLY_FILLED,
        }
        return status_map.get(status, cls.ERROR)

class OrderType(Enum):
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP = "STP"
    STOP_LIMIT = "STP LMT"

@dataclass
class OrderLeg:
    contract: Contract
    quantity: int
    action: str  # 'BUY' or 'SELL'
    order_type: OrderType
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    tws_order_id: Optional[int] = None
    filled_quantity: float = 0
    avg_fill_price: Optional[float] = None

@dataclass
class StrategyOrder:
    order_id: str
    legs: List[OrderLeg]
    status: OrderStatus
    created_time: datetime
    filled_time: Optional[datetime] = None
    error_message: Optional[str] = None
    description: str = ""

class OrderManager:
    def __init__(self, tws_connector):
        self.tws = tws_connector
        self.orders: Dict[str, StrategyOrder] = {}
        self.tws_to_strategy_map: Dict[int, str] = {}  # Maps TWS order IDs to strategy order IDs

    def create_order(self, legs: List[OrderLeg], description: str = "") -> str:
        """Create a new strategy order"""
        order_id = str(uuid.uuid4())
        strategy_order = StrategyOrder(
            order_id=order_id,
            legs=legs,
            status=OrderStatus.CREATED,
            created_time=datetime.now(),
            description=description
        )
        self.orders[order_id] = strategy_order
        return order_id

    def submit_order(self, order_id: str):
        """Submit an order to TWS"""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")
        
        strategy_order = self.orders[order_id]
        if strategy_order.status != OrderStatus.CREATED:
            raise ValueError(f"Order {order_id} is not in CREATED status")

        # Submit each leg
        for leg in strategy_order.legs:
            order = Order()
            order.orderType = leg.order_type.value
            order.totalQuantity = abs(leg.quantity)
            order.action = leg.action
            
            if leg.limit_price is not None:
                order.lmtPrice = leg.limit_price
            if leg.stop_price is not None:
                order.auxPrice = leg.stop_price

            # Get next order ID from TWS
            tws_order_id = self.tws.next_order_id
            self.tws.next_order_id += 1
            
            # Store mapping
            leg.tws_order_id = tws_order_id
            self.tws_to_strategy_map[tws_order_id] = order_id

            # Submit to TWS with validation
            try:
                self.tws.submit_order(leg.contract, order, tws_order_id)
            except Exception as e:
                print(f"Error submitting leg: {str(e)}")
                strategy_order.status = OrderStatus.ERROR
                strategy_order.error_message = str(e)
                return

        strategy_order.status = OrderStatus.SUBMITTED

    def update_order_status(self, tws_order_id: int, status: str, filled: float, remaining: float, avg_fill_price: float):
        """Update the status of an order leg"""
        if tws_order_id not in self.tws_to_strategy_map:
            return
            
        strategy_id = self.tws_to_strategy_map[tws_order_id]
        strategy_order = self.orders[strategy_id]
        
        # Update the specific leg
        for leg in strategy_order.legs:
            if leg.tws_order_id == tws_order_id:
                leg.filled_quantity = filled
                leg.avg_fill_price = avg_fill_price
                break
        
        # Update overall strategy status
        new_status = OrderStatus.from_tws_status(status)
        if new_status != strategy_order.status:
            strategy_order.status = new_status
            if new_status == OrderStatus.FILLED:
                strategy_order.filled_time = datetime.now()

    def cancel_order(self, order_id: str):
        """Cancel an order"""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")
        
        strategy_order = self.orders[order_id]
        if strategy_order.status not in [OrderStatus.SUBMITTED, OrderStatus.ACKNOWLEDGED, 
                                       OrderStatus.PRESUBMITTED, OrderStatus.PENDING_SUBMIT]:
            raise ValueError(f"Order {order_id} cannot be cancelled in {strategy_order.status} status")

        # Cancel each leg
        for leg in strategy_order.legs:
            if leg.tws_order_id is not None:
                self.tws.cancelOrder(leg.tws_order_id)

        strategy_order.status = OrderStatus.PENDING_CANCEL

    def get_order_status(self, order_id: str) -> OrderStatus:
        """Get the current status of an order"""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")
        return self.orders[order_id].status

    # Helper methods for creating common SPX option strategies
    def create_butterfly_order(
        self,
        center_strike: float,
        width: float,
        quantity: int,
        is_call: bool,
        expiry: str,
        order_type: OrderType = OrderType.LIMIT,
        limit_price: Optional[float] = None
    ) -> str:
        """Create a butterfly spread order"""
        right = "C" if is_call else "P"
        description = f"{'Call' if is_call else 'Put'} Butterfly {center_strike} ±{width} {expiry}"
        
        # Create the three legs
        legs = [
            OrderLeg(  # Buy lower strike
                contract=self.tws.get_spx_option_contract(right, center_strike - width, expiry),
                quantity=quantity,
                action="BUY",
                order_type=order_type,
                limit_price=limit_price
            ),
            OrderLeg(  # Sell center strike
                contract=self.tws.get_spx_option_contract(right, center_strike, expiry),
                quantity=quantity * 2,
                action="SELL",
                order_type=order_type,
                limit_price=limit_price
            ),
            OrderLeg(  # Buy upper strike
                contract=self.tws.get_spx_option_contract(right, center_strike + width, expiry),
                quantity=quantity,
                action="BUY",
                order_type=order_type,
                limit_price=limit_price
            )
        ]
        
        return self.create_order(legs, description)

    def create_calendar_order(
        self,
        strike: float,
        front_expiry: str,
        back_expiry: str,
        quantity: int,
        is_call: bool,
        order_type: OrderType = OrderType.LIMIT,
        limit_price: Optional[float] = None
    ) -> str:
        """Create a calendar spread order"""
        right = "C" if is_call else "P"
        description = f"{'Call' if is_call else 'Put'} Calendar {strike} {front_expiry}/{back_expiry}"
        
        legs = [
            OrderLeg(  # Sell front month
                contract=self.tws.get_spx_option_contract(right, strike, front_expiry),
                quantity=quantity,
                action="SELL",
                order_type=order_type,
                limit_price=limit_price
            ),
            OrderLeg(  # Buy back month
                contract=self.tws.get_spx_option_contract(right, strike, back_expiry),
                quantity=quantity,
                action="BUY",
                order_type=order_type,
                limit_price=limit_price
            )
        ]
        
        return self.create_order(legs, description)

    def create_double_calendar_order(
        self,
        strike: float,
        front_expiry: str,
        back_expiry: str,
        quantity: int,
        order_type: OrderType = OrderType.LIMIT,
        limit_price: Optional[float] = None
    ) -> str:
        """
        Create a double calendar spread order (both puts and calls)
        
        For automation considerations:
        - Assumes equal quantity for both put and call sides
        - Uses same strikes for both sides
        - Both sides are submitted as a single strategy for proper risk tracking
        """
        description = f"Double Calendar {strike} {front_expiry}/{back_expiry}"
        
        # Create put calendar legs
        put_legs = [
            OrderLeg(  # Sell front month put
                contract=self.tws.get_spx_option_contract("P", strike, front_expiry),
                quantity=quantity,
                action="SELL",
                order_type=order_type,
                limit_price=limit_price
            ),
            OrderLeg(  # Buy back month put
                contract=self.tws.get_spx_option_contract("P", strike, back_expiry),
                quantity=quantity,
                action="BUY",
                order_type=order_type,
                limit_price=limit_price
            )
        ]
        
        # Create call calendar legs
        call_legs = [
            OrderLeg(  # Sell front month call
                contract=self.tws.get_spx_option_contract("C", strike, front_expiry),
                quantity=quantity,
                action="SELL",
                order_type=order_type,
                limit_price=limit_price
            ),
            OrderLeg(  # Buy back month call
                contract=self.tws.get_spx_option_contract("C", strike, back_expiry),
                quantity=quantity,
                action="BUY",
                order_type=order_type,
                limit_price=limit_price
            )
        ]
        
        # Combine all legs
        legs = put_legs + call_legs
        return self.create_order(legs, description)

    def create_bag_order(
        self,
        legs: List[tuple[Contract, int]],  # List of (contract, quantity) pairs
        order_type: OrderType = OrderType.LIMIT,
        limit_price: Optional[float] = None
    ) -> str:
        """
        Create a BAG order from multiple legs
        legs: List of (contract, quantity) tuples where quantity is positive for buy, negative for sell
        """
        order_legs = []
        for contract, quantity in legs:
            action = "BUY" if quantity > 0 else "SELL"
            order_legs.append(
                OrderLeg(
                    contract=contract,
                    quantity=abs(quantity),
                    action=action,
                    order_type=order_type,
                    limit_price=limit_price
                )
            )
            
        description = "BAG Order: " + " + ".join(
            f"{leg.action} {leg.quantity} {leg.contract.right}{leg.contract.strike} {leg.contract.lastTradeDateOrContractMonth}"
            for leg in order_legs
        )
        
        return self.create_order(order_legs, description) 