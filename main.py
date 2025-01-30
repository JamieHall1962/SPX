import streamlit as st
import pandas as pd
from tws_connector import TWSConnector
from database import Database
from order_manager import OrderManager, OrderType, OrderStatus
import time
from datetime import datetime, timedelta
import queue

# Initialize session state
if 'tws' not in st.session_state:
    st.session_state.tws = TWSConnector(port=7496)
if 'db' not in st.session_state:
    st.session_state.db = Database()
if 'order_manager' not in st.session_state:
    st.session_state.order_manager = OrderManager(st.session_state.tws)
if 'spx_price' not in st.session_state:
    st.session_state.spx_price = None
if 'last_update' not in st.session_state:
    st.session_state.last_update = None

# Page config
st.set_page_config(page_title="SPX Options Dashboard", layout="wide")

# Header
col1, col2 = st.columns([3, 1])
with col1:
    st.title("SPX Options Trading Dashboard")
with col2:
    if st.button("Connect" if not st.session_state.tws.connected else "Disconnect"):
        if not st.session_state.tws.connected:
            st.session_state.tws.connect()
        else:
            st.session_state.tws.disconnect()

# Main layout
col1, col2 = st.columns(2)

# Account Status
with col1:
    st.subheader("Account Status")
    status_placeholder = st.empty()
    with status_placeholder.container():
        st.metric("Connection Status", "Connected" if st.session_state.tws.connected else "Disconnected")
        if st.session_state.tws.connected:
            if st.session_state.spx_price:
                price_str = f"${st.session_state.spx_price:,.2f}"
                if not st.session_state.tws.is_market_hours():
                    price_str += " (Last Close)"
                st.metric("SPX Price", price_str)
                if st.session_state.last_update:
                    st.caption(f"Last updated: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                st.metric("SPX Price", "Loading...")

# Current Positions
with col2:
    st.subheader("Current Positions")
    positions_placeholder = st.empty()
    if st.session_state.tws.connected and st.session_state.tws.positions:
        positions_data = []
        for pos in st.session_state.tws.positions.values():
            expiry = datetime.strptime(pos.contract.lastTradeDateOrContractMonth, '%Y%m%d').strftime('%Y-%m-%d')
            positions_data.append({
                'Type': f"{pos.contract.right} {pos.contract.strike}",
                'Expiry': expiry,
                'Pos': pos.position,
                'Avg Cost': f"${pos.avg_cost:.2f}",
                'Delta': f"{pos.delta:.2f}" if pos.delta is not None else "N/A",
                'Theta': f"{pos.theta:.2f}" if pos.theta is not None else "N/A"
            })
        if positions_data:
            df = pd.DataFrame(positions_data)
            positions_placeholder.dataframe(df, hide_index=True)
        else:
            positions_placeholder.text("No positions")
    else:
        positions_placeholder.text("No positions")

# Order Entry
st.subheader("Order Entry")
order_cols = st.columns(3)

with order_cols[0]:
    strategy_type = st.selectbox(
        "Strategy",
        ["Call Butterfly", "Put Butterfly", "Calendar", "Double Calendar", "Iron Condor"]
    )
    quantity = st.number_input("Quantity", min_value=1, value=1)
    order_type = st.selectbox("Order Type", ["LIMIT", "MARKET"])

with order_cols[1]:
    if strategy_type in ["Call Butterfly", "Put Butterfly"]:
        center_strike = st.number_input("Center Strike", min_value=0.0, step=5.0)
        wing_width = st.number_input("Wing Width", min_value=5.0, value=5.0, step=5.0)
        expiry = st.text_input("Expiry (YYYYMMDD)")
        limit_price = st.number_input("Limit Price", min_value=0.0, step=0.05) if order_type == "LIMIT" else None
        
        if st.button("Place Butterfly Order"):
            if st.session_state.tws.connected:
                is_call = strategy_type == "Call Butterfly"
                order_id = st.session_state.order_manager.create_butterfly_order(
                    center_strike=center_strike,
                    width=wing_width,
                    quantity=quantity,
                    is_call=is_call,
                    expiry=expiry,
                    order_type=OrderType.LIMIT if order_type == "LIMIT" else OrderType.MARKET,
                    limit_price=limit_price
                )
                st.session_state.order_manager.submit_order(order_id)
                st.success(f"Order submitted: {order_id}")
            else:
                st.error("Please connect to TWS first")

    elif strategy_type in ["Calendar", "Double Calendar"]:
        strike = st.number_input("Strike", min_value=0.0, step=5.0)
        front_expiry = st.text_input("Front Expiry (YYYYMMDD)")
        back_expiry = st.text_input("Back Expiry (YYYYMMDD)")
        
        # Only show call/put selection for regular calendar
        is_call = None
        if strategy_type == "Calendar":
            is_call = st.checkbox("Call (unchecked for Put)")
            
        limit_price = st.number_input("Limit Price", min_value=0.0, step=0.05) if order_type == "LIMIT" else None
        
        if st.button(f"Place {strategy_type} Order"):
            if st.session_state.tws.connected:
                if strategy_type == "Calendar":
                    order_id = st.session_state.order_manager.create_calendar_order(
                        strike=strike,
                        front_expiry=front_expiry,
                        back_expiry=back_expiry,
                        quantity=quantity,
                        is_call=is_call,
                        order_type=OrderType.LIMIT if order_type == "LIMIT" else OrderType.MARKET,
                        limit_price=limit_price
                    )
                else:  # Double Calendar
                    order_id = st.session_state.order_manager.create_double_calendar_order(
                        strike=strike,
                        front_expiry=front_expiry,
                        back_expiry=back_expiry,
                        quantity=quantity,
                        order_type=OrderType.LIMIT if order_type == "LIMIT" else OrderType.MARKET,
                        limit_price=limit_price
                    )
                st.session_state.order_manager.submit_order(order_id)
                st.success(f"Order submitted: {order_id}")
            else:
                st.error("Please connect to TWS first")

# Active Orders
with order_cols[2]:
    st.subheader("Active Orders")
    active_orders = [
        order for order in st.session_state.order_manager.orders.values()
        if order.status not in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.ERROR]
    ]
    
    if active_orders:
        for order in active_orders:
            with st.container():
                st.markdown(f"**{order.description}**")
                col1, col2 = st.columns([3, 1])
                with col1:
                    status_color = {
                        OrderStatus.CREATED: "🟡",
                        OrderStatus.SUBMITTED: "🟡",
                        OrderStatus.PENDING_SUBMIT: "🟡",
                        OrderStatus.PRESUBMITTED: "🟡",
                        OrderStatus.ACKNOWLEDGED: "🟢",
                        OrderStatus.PARTIALLY_FILLED: "🟢",
                        OrderStatus.PENDING_CANCEL: "🔴",
                    }.get(order.status, "⚪")
                    
                    st.text(f"{status_color} Status: {order.status.value}")
                    
                    # Show leg details
                    for leg in order.legs:
                        fill_status = ""
                        if leg.filled_quantity > 0:
                            fill_status = f" (Filled: {leg.filled_quantity} @ ${leg.avg_fill_price:.2f})"
                        st.text(f"  └ {leg.action} {abs(leg.quantity)} @ {leg.contract.strike}{fill_status}")
                
                with col2:
                    if order.status not in [OrderStatus.CANCELLED, OrderStatus.PENDING_CANCEL]:
                        if st.button("Cancel", key=f"cancel_{order.order_id}"):
                            st.session_state.order_manager.cancel_order(order.order_id)
    else:
        st.text("No active orders")
    
# Risk Panel
st.subheader("Risk Panel")
risk_cols = st.columns(3)
with risk_cols[0]:
    total_delta = st.session_state.tws.get_total_delta() if st.session_state.tws.connected else 0
    st.metric("Total Delta Exposure", f"{total_delta:.2f}")
with risk_cols[1]:
    max_risk = st.session_state.tws.get_max_risk() if st.session_state.tws.connected else 0
    risk_str = "∞" if max_risk == float('inf') else f"${max_risk:,.2f}"
    st.metric("Max Risk", risk_str)
with risk_cols[2]:
    num_positions = len(st.session_state.tws.positions) if st.session_state.tws.connected else 0
    st.metric("Open Positions", str(num_positions))

# Trade History
st.subheader("Trade History")
trade_history_placeholder = st.empty()

# Update loop
def update_data():
    if st.session_state.tws.connected:
        # Request market data
        st.session_state.tws.request_spx_data()
        st.session_state.tws.request_positions()
        
        # Process data from queue
        try:
            while True:
                msg = st.session_state.tws.data_queue.get_nowait()
                if msg[0] == 'price':
                    _, _, tick_type, price = msg
                    if tick_type == 4:  # Last price
                        st.session_state.spx_price = price
                        st.session_state.last_update = datetime.now()
                elif msg[0] == 'historical':
                    _, _, bar = msg
                    st.session_state.spx_price = bar.close
                    st.session_state.last_update = datetime.strptime(bar.date, '%Y%m%d')
                elif msg[0] == 'position':
                    pass  # Handled in TWS connector
                elif msg[0] == 'option_tick':
                    _, req_id, tick_type, impl_vol, delta, gamma, vega, theta = msg
                    # Update option position with market data
                    pass
                elif msg[0] == 'request_option_data':
                    _, contract = msg
                    st.session_state.tws.request_option_data(contract)
                elif msg[0] == 'order_status':
                    _, order_id, status, filled, remaining, avg_fill_price = msg
                    st.session_state.order_manager.update_order_status(
                        order_id, status, filled, remaining, avg_fill_price
                    )
                elif msg[0] == 'error':
                    _, req_id, error_code, error_msg = msg
                    st.error(f"TWS Error {error_code}: {error_msg}")
        except queue.Empty:
            pass
        except Exception as e:
            st.error(f"Error processing updates: {str(e)}")

if st.session_state.tws.connected:
    update_data()

# Auto-refresh every 5 seconds
time.sleep(5)
st.rerun() 