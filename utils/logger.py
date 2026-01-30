import logging
import sys
import os
from datetime import datetime
from typing import Optional, Dict, Any
import json

class EnterpriseLogger:
    def __init__(self, name: str, component: str = None, log_level: str = "INFO"):
        self.name = name
        self.component = component or name
        self.logger = logging.getLogger(f"{name}.{component}")
        self.logger.handlers.clear()
        level = getattr(logging, log_level.upper(), logging.INFO)
        self.logger.setLevel(level)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        self.logger.addHandler(console_handler)
        log_dir = "/tmp/quant_logs"
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"{name}_{timestamp}.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        self.metrics = {'info': 0, 'warning': 0, 'error': 0, 'critical': 0, 'debug': 0}
        self.logger.propagate = False

    def _format_message(self, message: str, **kwargs) -> str:
        if kwargs:
            context_str = " ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"{message} | {context_str}"
        return message

    def info(self, message: str, **kwargs):
        self.metrics['info'] += 1
        self.logger.info(self._format_message(message, **kwargs))

    def warning(self, message: str, **kwargs):
        self.metrics['warning'] += 1
        self.logger.warning(self._format_message(message, **kwargs))

    def error(self, message: str, **kwargs):
        self.metrics['error'] += 1
        self.logger.error(self._format_message(message, **kwargs))

    def critical(self, message: str, **kwargs):
        self.metrics['critical'] += 1
        self.logger.critical(self._format_message(message, **kwargs))

    def debug(self, message: str, **kwargs):
        self.metrics['debug'] += 1
        self.logger.debug(self._format_message(message, **kwargs))

    def trade(self, trade_data: Dict[str, Any]):
        self.info(f"TRADE: {json.dumps(trade_data, default=str)}")

    def performance(self, metrics: Dict[str, Any]):
        self.info(f"PERFORMANCE: {json.dumps(metrics, default=str)}")

    def get_metrics(self) -> Dict[str, int]:
        return self.metrics.copy()

    def reset_metrics(self):
        for key in self.metrics:
            self.metrics[key] = 0

def setup_logger(name: str, log_level: str = "INFO", log_to_file: bool = True) -> logging.Logger:
    logger = EnterpriseLogger(name, log_level=log_level)
    return logger.logger

def get_logger(name: str) -> logging.Logger:
    return setup_logger(name)