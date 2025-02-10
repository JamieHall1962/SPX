from dataclasses import dataclass
from typing import Optional, Dict, List, Callable
import logging

@dataclass
class RiskThresholds:
    """Risk thresholds for DC trades"""
    max_abs_delta: float = 0.40        # Maximum absolute delta
    max_contracts: int = 1             # Maximum position size
    max_loss_pct: float = 0.50        # Maximum loss as % of max profit
    min_vix: float = 10.0             # Minimum VIX level for entry
    
@dataclass
class RiskStatus:
    """Current risk status"""
    abs_delta: float
    position_size: int
    unrealized_pnl: float
    max_profit: float
    vix_level: float
    breached_thresholds: List[str]

class RiskMonitor:
    def __init__(self, thresholds: Optional[RiskThresholds] = None):
        self.thresholds = thresholds or RiskThresholds()
        self.risk_callbacks: List[Callable[[str, Dict], None]] = []
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - RISK - %(message)s'
        )
    
    def add_risk_callback(self, callback: Callable[[str, Dict], None]):
        """Add callback for risk events"""
        self.risk_callbacks.append(callback)
    
    def _notify_risk_event(self, event: str, details: Dict):
        """Notify all callbacks of risk event"""
        logging.warning(f"Risk Event: {event} - {details}")
        for callback in self.risk_callbacks:
            try:
                callback(event, details)
            except Exception as e:
                logging.error(f"Error in risk callback: {e}")
    
    def check_position_risk(self, position) -> RiskStatus:
        """Check all risk metrics for a position"""
        breached = []
        
        # Calculate current metrics
        abs_delta = abs(position.delta) if position.delta else 0
        unrealized_pnl = position.unrealized_pnl if hasattr(position, 'unrealized_pnl') else 0
        max_profit = position.max_profit if hasattr(position, 'max_profit') else 0
        
        # Check delta risk
        if abs_delta > self.thresholds.max_abs_delta:
            event = "DELTA_BREACH"
            details = {"current": abs_delta, "threshold": self.thresholds.max_abs_delta}
            self._notify_risk_event(event, details)
            breached.append(event)
        
        # Check position size
        if abs(position.position) > self.thresholds.max_contracts:
            event = "SIZE_BREACH"
            details = {"current": position.position, "threshold": self.thresholds.max_contracts}
            self._notify_risk_event(event, details)
            breached.append(event)
        
        # Check P&L if we have the data
        if unrealized_pnl and max_profit:
            loss_pct = abs(unrealized_pnl) / max_profit
            if loss_pct > self.thresholds.max_loss_pct:
                event = "LOSS_BREACH"
                details = {"current": loss_pct, "threshold": self.thresholds.max_loss_pct}
                self._notify_risk_event(event, details)
                breached.append(event)
        
        return RiskStatus(
            abs_delta=abs_delta,
            position_size=abs(position.position),
            unrealized_pnl=unrealized_pnl,
            max_profit=max_profit,
            vix_level=0,  # Need to add VIX monitoring
            breached_thresholds=breached
        )

    def should_exit_position(self, status: RiskStatus) -> bool:
        """Determine if position should be exited based on risk"""
        return len(status.breached_thresholds) > 0
