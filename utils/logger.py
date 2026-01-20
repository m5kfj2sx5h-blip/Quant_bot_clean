"""
Professional logging system for the arbitrage bot
"""

import logging
import sys
import os
from datetime import datetime
from typing import Optional, Dict, Any
import json

class EnterpriseLogger:
    """Enterprise-grade logger with structured logging"""
    
    def __init__(self, name: str, component: str = None, log_level: str = "INFO"):
        self.name = name
        self.component = component or name
        self.logger = logging.getLogger(f"{name}.{component}")
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Set level
        level = getattr(logging, log_level.upper(), logging.INFO)
        self.logger.setLevel(level)
        
        # Console handler with color formatting
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        
        # Professional formatter
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(console_handler)
        
        # File handler for persistence
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file = os.path.join(log_dir, f"{name}_{timestamp}.log")
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # Metrics tracking
        self.metrics = {
            'info': 0,
            'warning': 0,
            'error': 0,
            'critical': 0,
            'debug': 0
        }
        
        self.logger.propagate = False
    
    def _format_message(self, message: str, **kwargs) -> str:
        """Format message with optional context"""
        if kwargs:
            context_str = " ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"{message} | {context_str}"
        return message
    
    def info(self, message: str, **kwargs):
        """Log info message"""
        self.metrics['info'] += 1
        self.logger.info(self._format_message(message, **kwargs))
    
    def warning(self, message: str, **kwargs):
        """Log warning message"""
        self.metrics['warning'] += 1
        self.logger.warning(self._format_message(message, **kwargs))
    
    def error(self, message: str, **kwargs):
        """Log error message"""
        self.metrics['error'] += 1
        self.logger.error(self._format_message(message, **kwargs))
    
    def critical(self, message: str, **kwargs):
        """Log critical message"""
        self.metrics['critical'] += 1
        self.logger.critical(self._format_message(message, **kwargs))
    
    def debug(self, message: str, **kwargs):
        """Log debug message"""
        self.metrics['debug'] += 1
        self.logger.debug(self._format_message(message, **kwargs))
    
    def trade(self, trade_data: Dict[str, Any]):
        """Log structured trade data"""
        self.info(f"TRADE: {json.dumps(trade_data, default=str)}")
    
    def performance(self, metrics: Dict[str, Any]):
        """Log performance metrics"""
        self.info(f"PERFORMANCE: {json.dumps(metrics, default=str)}")
    
    def get_metrics(self) -> Dict[str, int]:
        """Get logging metrics"""
        return self.metrics.copy()
    
    def reset_metrics(self):
        """Reset metrics counters"""
        for key in self.metrics:
            self.metrics[key] = 0

def setup_logger(
    name: str,
    log_level: str = "INFO",
    log_to_file: bool = True
) -> logging.Logger:
    """
    Quick setup for standard logger
    
    Args:
        name: Logger name
        log_level: Logging level
        log_to_file: Whether to log to file
        
    Returns:
        Configured logger
    """
    logger = EnterpriseLogger(name, log_level=log_level)
    return logger

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance"""
    return setup_logger(name)