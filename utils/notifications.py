import logging
import smtplib
import ssl
from email.message import EmailMessage
import requests
from datetime import datetime

from config.settings import (
    ENABLE_EMAIL_NOTIFICATIONS, EMAIL_NOTIFICATION_ADDRESS,
    ENABLE_TEXT_NOTIFICATIONS, TEXT_NOTIFICATION_NUMBER
)
from utils.logging_utils import setup_logger

# Set up logger
logger = setup_logger("notifications")

def send_email_notification(subject, message):
    """
    Send an email notification
    
    Args:
        subject: Email subject
        message: Email message
        
    Returns:
        bool: True if sent successfully, False otherwise
    """
    if not ENABLE_EMAIL_NOTIFICATIONS:
        logger.debug("Email notifications disabled")
        return False
    
    if not EMAIL_NOTIFICATION_ADDRESS:
        logger.error("Email address not configured")
        return False
    
    try:
        # This is a placeholder - in a real implementation
        # you would configure your SMTP settings and send the email
        logger.info(f"Sending email notification to {EMAIL_NOTIFICATION_ADDRESS}")
        logger.info(f"Subject: {subject}")
        logger.info(f"Message: {message}")
        
        # Placeholder for actual email sending code
        # Example implementation:
        """
        msg = EmailMessage()
        msg.set_content(message)
        msg['Subject'] = subject
        msg['From'] = 'spx_trader@example.com'
        msg['To'] = EMAIL_NOTIFICATION_ADDRESS
        
        # Send the message via SMTP server
        with smtplib.SMTP_SSL('smtp.example.com', 465, context=ssl.create_default_context()) as server:
            server.login('username', 'password')
            server.send_message(msg)
        """
        
        return True
    
    except Exception as e:
        logger.error(f"Failed to send email notification: {e}")
        return False

def send_text_notification(message):
    """
    Send a text message notification
    
    Args:
        message: Text message
        
    Returns:
        bool: True if sent successfully, False otherwise
    """
    if not ENABLE_TEXT_NOTIFICATIONS:
        logger.debug("Text notifications disabled")
        return False
    
    if not TEXT_NOTIFICATION_NUMBER:
        logger.error("Text notification number not configured")
        return False
    
    try:
        # This is a placeholder - in a real implementation
        # you would use a service like Twilio or an SMS gateway
        logger.info(f"Sending text notification to {TEXT_NOTIFICATION_NUMBER}")
        logger.info(f"Message: {message}")
        
        # Placeholder for actual SMS sending code
        # Example implementation with Twilio:
        """
        from twilio.rest import Client
        
        account_sid = 'your_account_sid'
        auth_token = 'your_auth_token'
        client = Client(account_sid, auth_token)
        
        message = client.messages.create(
            body=message,
            from_='+1234567890',  # Your Twilio number
            to=TEXT_NOTIFICATION_NUMBER
        )
        """
        
        return True
    
    except Exception as e:
        logger.error(f"Failed to send text notification: {e}")
        return False

def notify_error(error_message):
    """
    Send notification about an error
    
    Args:
        error_message: Error message
        
    Returns:
        bool: True if notification sent successfully, False otherwise
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"SPX Trader Error - {timestamp}"
    message = f"Error: {error_message}\nTime: {timestamp}"
    
    logger.error(f"System error: {error_message}")
    
    # Send email notification
    email_sent = send_email_notification(subject, message)
    
    # Send text notification
    text_sent = send_text_notification(f"SPX Trader Error: {error_message}")
    
    return email_sent or text_sent

def notify_trade_executed(trade_info):
    """
    Send notification about an executed trade
    
    Args:
        trade_info: Dictionary with trade information
        
    Returns:
        bool: True if notification sent successfully, False otherwise
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"SPX Trader - Trade Executed - {timestamp}"
    
    # Format the message
    message = "Trade Executed:\n"
    message += f"Order ID: {trade_info.get('order_id', 'N/A')}\n"
    message += f"Status: {trade_info.get('status', 'N/A')}\n"
    message += f"Filled: {trade_info.get('filled', 0)}\n"
    message += f"Price: ${trade_info.get('avg_fill_price', 0):.2f}\n"
    message += f"Time: {trade_info.get('filled_time', timestamp)}"
    
    logger.info(f"Trade executed: {trade_info}")
    
    # Send email notification
    email_sent = send_email_notification(subject, message)
    
    # Send text notification (shorter version)
    text_message = f"Trade executed: {trade_info.get('filled', 0)} at ${trade_info.get('avg_fill_price', 0):.2f}"
    text_sent = send_text_notification(text_message)
    
    return email_sent or text_sent

def notify_position_closed(position_info):
    """
    Send notification about a closed position
    
    Args:
        position_info: Dictionary with position information
        
    Returns:
        bool: True if notification sent successfully, False otherwise
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"SPX Trader - Position Closed - {timestamp}"
    
    # Format the message
    message = "Position Closed:\n"
    message += f"Symbol: {position_info.get('symbol', 'N/A')}\n"
    message += f"Strategy: {position_info.get('strategy', 'N/A')}\n"
    message += f"P&L: ${position_info.get('pnl', 0):.2f}\n"
    message += f"P&L %: {position_info.get('pnl_percent', 0):.2f}%\n"
    message += f"Open Time: {position_info.get('open_time', 'N/A')}\n"
    message += f"Close Time: {position_info.get('close_time', timestamp)}"
    
    logger.info(f"Position closed: {position_info}")
    
    # Send email notification
    email_sent = send_email_notification(subject, message)
    
    # Send text notification (shorter version)
    text_message = f"Position closed: {position_info.get('symbol', 'N/A')} P&L: ${position_info.get('pnl', 0):.2f} ({position_info.get('pnl_percent', 0):.2f}%)"
    text_sent = send_text_notification(text_message)
    
    return email_sent or text_sent

def notify_status_update(status_message):
    """
    Send a general status update notification
    
    Args:
        status_message: Status message
        
    Returns:
        bool: True if notification sent successfully, False otherwise
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"SPX Trader - Status Update - {timestamp}"
    
    # Format the message
    message = f"Status Update: {status_message}\n"
    message += f"Time: {timestamp}"
    
    logger.info(f"Status update: {status_message}")
    
    # Send email notification
    email_sent = send_email_notification(subject, message)
    
    # Send text notification
    text_sent = send_text_notification(f"SPX Trader: {status_message}")
    
    return email_sent or text_sent
