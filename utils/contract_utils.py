import datetime
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.common import BarData
from typing import List, Dict, Tuple, Optional

from config.settings import DEFAULT_EXCHANGE, DEFAULT_CURRENCY
from utils.logging_utils import setup_logger

# Set up logger
logger = setup_logger("contract_utils")

def create_spx_index_contract() -> Contract:
    """
    Create a contract for SPX index
    
    Returns:
        Contract: SPX index contract
    """
    contract = Contract()
    contract.symbol = "SPX"
    contract.secType = "IND"
    contract.exchange = DEFAULT_EXCHANGE
    contract.currency = DEFAULT_CURRENCY
    
    return contract

def create_spx_option_contract(expiry: str, strike: float, option_type: str) -> Contract:
    """
    Create a contract for SPX option
    
    Args:
        expiry: Option expiration date in YYYYMMDD format
        strike: Strike price
        option_type: "C" for call, "P" for put
        
    Returns:
        Contract: SPX option contract
    """
    contract = Contract()
    contract.symbol = "SPX"
    contract.secType = "OPT"
    contract.exchange = DEFAULT_EXCHANGE
    contract.currency = DEFAULT_CURRENCY
    contract.lastTradeDateOrContractMonth = expiry
    contract.strike = strike
    contract.right = "C" if option_type == "C" else "P"
    contract.multiplier = "100"
    
    return contract

def create_iron_condor_contract(expiry: str, strikes: List[float]) -> Contract:
    """
    Create a contract for an iron condor combo
    
    Args:
        expiry: Option expiration date in YYYYMMDD format
        strikes: List of 4 strikes [long put, short put, short call, long call]
        
    Returns:
        Contract: Iron condor combo contract
    """
    # Verify we have 4 strikes
    if len(strikes) != 4:
        logger.error(f"Iron condor requires 4 strikes, got {len(strikes)}")
        return None
    
    contract = Contract()
    contract.symbol = "SPX"
    contract.secType = "BAG"
    contract.exchange = DEFAULT_EXCHANGE
    contract.currency = DEFAULT_CURRENCY
    
    # Define the legs
    leg1 = ComboLeg()
    leg1.conId = 0  # This will be replaced by IB
    leg1.ratio = 1
    leg1.action = "BUY"
    leg1.exchange = DEFAULT_EXCHANGE
    
    leg2 = ComboLeg()
    leg2.conId = 0  # This will be replaced by IB
    leg2.ratio = 1
    leg2.action = "SELL"
    leg2.exchange = DEFAULT_EXCHANGE
    
    leg3 = ComboLeg()
    leg3.conId = 0  # This will be replaced by IB
    leg3.ratio = 1
    leg3.action = "SELL"
    leg3.exchange = DEFAULT_EXCHANGE
    
    leg4 = ComboLeg()
    leg4.conId = 0  # This will be replaced by IB
    leg4.ratio = 1
    leg4.action = "BUY"
    leg4.exchange = DEFAULT_EXCHANGE
    
    contract.comboLegs = [leg1, leg2, leg3, leg4]
    
    # In real implementation, we would need to use the contract IDs
    # of the individual options, which requires querying IB first
    # This is a simplified version
    
    return contract

def create_butterfly_contract(expiry: str, strikes: List[float], option_type: str) -> Contract:
    """
    Create a contract for a butterfly combo
    
    Args:
        expiry: Option expiration date in YYYYMMDD format
        strikes: List of 3 strikes [low, middle, high]
        option_type: "C" for call butterfly, "P" for put butterfly
        
    Returns:
        Contract: Butterfly combo contract
    """
    # Verify we have 3 strikes
    if len(strikes) != 3:
        logger.error(f"Butterfly requires 3 strikes, got {len(strikes)}")
        return None
    
    contract = Contract()
    contract.symbol = "SPX"
    contract.secType = "BAG"
    contract.exchange = DEFAULT_EXCHANGE
    contract.currency = DEFAULT_CURRENCY
    
    # Define the legs
    leg1 = ComboLeg()
    leg1.conId = 0  # This will be replaced by IB
    leg1.ratio = 1
    leg1.action = "BUY"
    leg1.exchange = DEFAULT_EXCHANGE
    
    leg2 = ComboLeg()
    leg2.conId = 0  # This will be replaced by IB
    leg2.ratio = 2
    leg2.action = "SELL"
    leg2.exchange = DEFAULT_EXCHANGE
    
    leg3 = ComboLeg()
    leg3.conId = 0  # This will be replaced by IB
    leg3.ratio = 1
    leg3.action = "BUY"
    leg3.exchange = DEFAULT_EXCHANGE
    
    contract.comboLegs = [leg1, leg2, leg3]
    
    # In real implementation, we would need to use the contract IDs
    # of the individual options, which requires querying IB first
    # This is a simplified version
    
    return contract

def create_calendar_contract(strikes: List[float], expiries: List[str], option_type: str) -> Contract:
    """
    Create a contract for a calendar spread
    
    Args:
        strikes: List containing the strike price
        expiries: List of 2 expiry dates [near, far]
        option_type: "C" for call calendar, "P" for put calendar
        
    Returns:
        Contract: Calendar spread contract
    """
    # Verify we have 1 strike and 2 expiries
    if len(strikes) != 1:
        logger.error(f"Calendar requires 1 strike, got {len(strikes)}")
        return None
    
    if len(expiries) != 2:
        logger.error(f"Calendar requires 2 expiries, got {len(expiries)}")
        return None
    
    contract = Contract()
    contract.symbol = "SPX"
    contract.secType = "BAG"
    contract.exchange = DEFAULT_EXCHANGE
    contract.currency = DEFAULT_CURRENCY
    
    # Define the legs
    leg1 = ComboLeg()
    leg1.conId = 0  # This will be replaced by IB
    leg1.ratio = 1
    leg1.action = "SELL"
    leg1.exchange = DEFAULT_EXCHANGE
    
    leg2 = ComboLeg()
    leg2.conId = 0  # This will be replaced by IB
    leg2.ratio = 1
    leg2.action = "BUY"
    leg2.exchange = DEFAULT_EXCHANGE
    
    contract.comboLegs = [leg1, leg2]
    
    # In real implementation, we would need to use the contract IDs
    # of the individual options, which requires querying IB first
    # This is a simplified version
    
    return contract

def create_limit_order(action: str, quantity: int, limit_price: float) -> Order:
    """
    Create a limit order
    
    Args:
        action: "BUY" or "SELL"
        quantity: Number of contracts
        limit_price: Limit price
        
    Returns:
        Order: Limit order
    """
    order = Order()
    order.action = action
    order.totalQuantity = quantity
    order.orderType = "LMT"
    order.lmtPrice = limit_price
    
    return order

def create_market_order(action: str, quantity: int) -> Order:
    """
    Create a market order
    
    Args:
        action: "BUY" or "SELL"
        quantity: Number of contracts
        
    Returns:
        Order: Market order
    """
    order = Order()
    order.action = action
    order.totalQuantity = quantity
    order.orderType = "MKT"
    
    return order

def create_stop_order(action: str, quantity: int, stop_price: float) -> Order:
    """
    Create a stop order
    
    Args:
        action: "BUY" or "SELL"
        quantity: Number of contracts
        stop_price: Stop price
        
    Returns:
        Order: Stop order
    """
    order = Order()
    order.action = action
    order.totalQuantity = quantity
    order.orderType = "STP"
    order.auxPrice = stop_price
    
    return order

def calculate_expiry_date(dte: int) -> str:
    """
    Calculate expiry date given days to expiration
    
    Args:
        dte: Days to expiration
        
    Returns:
        str: Expiry date in YYYYMMDD format
    """
    # Simple calculation (doesn't account for holidays)
    today = datetime.date.today()
    expiry = today + datetime.timedelta(days=dte)
    return expiry.strftime("%Y%m%d")

def get_option_expiries(tws_connector) -> List[str]:
    """
    Get available option expiries for SPX
    
    Args:
        tws_connector: TWS connector instance
        
    Returns:
        List[str]: List of available expiries in YYYYMMDD format
    """
    # This would be implemented using the tws_connector to query
    # available expiries from TWS
    # Placeholder implementation
    return []

def get_option_strikes(tws_connector, expiry: str) -> List[float]:
    """
    Get available strikes for SPX for a given expiry
    
    Args:
        tws_connector: TWS connector instance
        expiry: Option expiration date in YYYYMMDD format
        
    Returns:
        List[float]: List of available strikes
    """
    # This would be implemented using the tws_connector to query
    # available strikes from TWS
    # Placeholder implementation
    return []

def get_nearest_expiry(expiries: List[str]) -> str:
    """
    Get the nearest expiry date from a list of expiries
    
    Args:
        expiries: List of expiry dates in YYYYMMDD format
        
    Returns:
        str: Nearest expiry date in YYYYMMDD format
    """
    if not expiries:
        return None
    
    today = datetime.date.today()
    
    # Convert expiries to datetime objects
    expiry_dates = []
    for expiry in expiries:
        try:
            year = int(expiry[:4])
            month = int(expiry[4:6])
            day = int(expiry[6:8])
            expiry_dates.append(datetime.date(year, month, day))
        except (ValueError, IndexError):
            logger.warning(f"Invalid expiry format: {expiry}")
    
    # Find the nearest expiry
    nearest_expiry = min(expiry_dates, key=lambda x: abs((x - today).days))
    
    return nearest_expiry.strftime("%Y%m%d")
