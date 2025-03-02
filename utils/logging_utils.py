import os
import logging
from logging.handlers import TimedRotatingFileHandler
import sys
from pathlib import Path

from config.settings import (
    LOG_DIR, LOG_LEVEL, LOG_FORMAT, LOG_TO_CONSOLE, 
    LOG_TO_FILE, LOG_ROTATION, LOG_RETENTION
)

def setup_logger(name):
    """
    Set up and configure a logger
    
    Args:
        name: Name of the logger
        
    Returns:
        logging.Logger: Configured logger
    """
    # Create logger
    logger = logging.getLogger(name)
    
    # Only configure handlers if none exist (prevent duplicate handlers)
    if not logger.handlers:
        # Set log level
        level = getattr(logging, LOG_LEVEL) if isinstance(LOG_LEVEL, str) else LOG_LEVEL
        logger.setLevel(level)
        
        # Create formatters
        formatter = logging.Formatter(LOG_FORMAT)
        
        # Add console handler if enabled
        if LOG_TO_CONSOLE:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        
        # Add file handler if enabled
        if LOG_TO_FILE:
            # Create log directory if it doesn't exist
            Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
            
            # Determine log file name
            log_file = os.path.join(LOG_DIR, f"{name}.log")
            
            # Create timed rotating file handler
            if LOG_ROTATION == "midnight":
                file_handler = TimedRotatingFileHandler(
                    log_file, when="midnight", backupCount=LOG_RETENTION
                )
            elif LOG_ROTATION == "h":
                file_handler = TimedRotatingFileHandler(
                    log_file, when="h", interval=1, backupCount=LOG_RETENTION * 24
                )
            else:
                # Default to daily rotation
                file_handler = TimedRotatingFileHandler(
                    log_file, when="midnight", backupCount=LOG_RETENTION
                )
            
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
    
    return logger
