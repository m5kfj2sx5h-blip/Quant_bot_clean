"""
Configuration management for the arbitrage bot
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path

class ConfigManager:
    """Professional configuration manager"""
    
    def __init__(self, config_path: str = "config/bot_config.json"):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.defaults = self._get_defaults()
        
    def _get_defaults(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            "exchanges": {
                "kraken": {"enabled": True, "api_key": "", "api_secret": ""},
                "binance": {"enabled": True, "api_key": "", "api_secret": ""},
                "coinbase": {"enabled": True, "api_key": "", "api_secret": ""}
            },
            "trading": {
                "pairs": ["BTC/USDT"],
                "position_size": 500,
                "min_profit": 0.5,
                "max_position": 1000
            },
            "capital": {
                "mode": "dynamic",
                "min_per_exchange": 1500,
                "bottleneck_ratio": 1.5,
                "balanced_allocation": 0.4,
                "bottleneck_allocation": 0.95
            },
            "performance": {
                "max_consecutive_losses": 3,
                "cooldown_minutes": 5,
                "max_drawdown_percent": 10
            }
        }
    
    def load(self) -> Dict[str, Any]:
        """Load configuration from file"""
        config_dir = os.path.dirname(self.config_path)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir)
        
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
        else:
            self.config = self.defaults.copy()
            self.save()
        
        return self.config
    
    def save(self, config: Optional[Dict[str, Any]] = None):
        """Save configuration to file"""
        if config:
            self.config = config
        
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with dot notation"""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any):
        """Set configuration value with dot notation"""
        keys = key.split('.')
        config = self.config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
        self.save()

def load_config(config_path: str = "config/bot_config.json") -> Dict[str, Any]:
    """Quick config loader"""
    manager = ConfigManager(config_path)
    return manager.load()

def save_config(config: Dict[str, Any], config_path: str = "config/bot_config.json"):
    """Quick config saver"""
    manager = ConfigManager(config_path)
    manager.save(config)