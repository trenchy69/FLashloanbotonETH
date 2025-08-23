# config/settings.py
import os
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

@dataclass
class TradingPaths:
    """Define the 4 trading paths from your FlashSwap contract"""
    
    # Path 1: WETH -> USDC -> WETH
    PATH_1 = {
        'id': 1,
        'name': 'WETH->USDC->WETH',
        'tokens': ['WETH', 'USDC'],
        'dexes': ['Uniswap', 'Sushiswap'],
        'description': 'WETH to USDC on Uniswap, USDC to WETH on Sushiswap'
    }
    
    # Path 2: WETH -> USDT -> WETH  
    PATH_2 = {
        'id': 2,
        'name': 'WETH->USDT->WETH',
        'tokens': ['WETH', 'USDT'],
        'dexes': ['Uniswap', 'Sushiswap'],
        'description': 'WETH to USDT on Uniswap, USDT to WETH on Sushiswap'
    }
    
    # Path 3: WETH -> DAI -> WETH
    PATH_3 = {
        'id': 3,
        'name': 'WETH->DAI->WETH',
        'tokens': ['WETH', 'DAI'],
        'dexes': ['Uniswap', 'Sushiswap'],
        'description': 'WETH to DAI on Uniswap, DAI to WETH on Sushiswap'
    }
    
    # Path 4: WETH -> WBTC -> WETH
    PATH_4 = {
        'id': 4,
        'name': 'WETH->WBTC->WETH',
        'tokens': ['WETH', 'WBTC'],
        'dexes': ['Uniswap', 'Sushiswap'],
        'description': 'WETH to WBTC on Uniswap, WBTC to WETH on Sushiswap'
    }
    
    @classmethod
    def get_all_paths(cls) -> List[Dict]:
        return [cls.PATH_1, cls.PATH_2, cls.PATH_3, cls.PATH_4]
    
    @classmethod
    def get_path_by_id(cls, path_id: int) -> Optional[Dict]:
        paths = cls.get_all_paths()
        return next((path for path in paths if path['id'] == path_id), None)

@dataclass
class TokenAddresses:
    """Mainnet token addresses"""
    WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    USDC = "0xA0b86a33E6441e94c7612Fd84C1C563bf69F7D0F" 
    USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    DAI = "0x6B175474E89094C44Da98b954EedeAC495271d0F"
    WBTC = "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"

@dataclass  
class DexAddresses:
    """DEX router and factory addresses"""
    
    # Uniswap V2
    UNISWAP_V2_ROUTER = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
    UNISWAP_V2_FACTORY = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
    
    # Sushiswap
    SUSHISWAP_ROUTER = "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F"
    SUSHISWAP_FACTORY = "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac"

class DynamicConfig:
    """Dynamic configuration that can be updated at runtime via Telegram"""
    
    def __init__(self):
        self.config_file = Path('config/user_config.json')
        self.load_config()
    
    def load_config(self):
        """Load configuration from file or create defaults"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                self._config = json.load(f)
        else:
            self._config = self._default_config()
            self.save_config()
    
    def save_config(self):
        """Save current configuration to file"""
        self.config_file.parent.mkdir(exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(self._config, f, indent=2)
    
    def _default_config(self) -> Dict[str, Any]:
        """Default dynamic configuration"""
        return {
            'scanner': {
                'min_profit_eth': float(os.getenv('MIN_PROFIT_ETH', 0.01)),
                'max_gas_price': int(os.getenv('MAX_GAS_PRICE', 50)),
                'scan_interval': int(os.getenv('SCAN_INTERVAL', 5)),
                'enabled_paths': [1, 2, 3, 4],  # All paths enabled by default
                'auto_execution_enabled': os.getenv('AUTO_EXECUTION_ENABLED', 'false').lower() == 'true'
            },
            'risk': {
                'max_trade_size': float(os.getenv('MAX_TRADE_SIZE', 5.0)),
                'max_slippage': float(os.getenv('MAX_SLIPPAGE', 0.5)),
                'auto_execute_threshold': float(os.getenv('AUTO_EXECUTE_THRESHOLD', 0.05))
            },
            'alerts': {
                'telegram_enabled': True,
                'min_profit_for_alert': 0.005,  # Alert for opportunities above 0.005 ETH
                'urgent_alert_threshold': 0.1   # Urgent alerts for big opportunities
            },
            'advanced': {
                'use_flashloans': True,
                'competition_protection': True,
                'gas_optimization': True
            }
        }
    
    def get(self, key_path: str, default=None):
        """Get configuration value using dot notation (e.g., 'scanner.min_profit_eth')"""
        keys = key_path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def set(self, key_path: str, value: Any):
        """Set configuration value using dot notation"""
        keys = key_path.split('.')
        config = self._config
        
        # Navigate to the parent of the target key
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        
        # Set the final value
        config[keys[-1]] = value
        self.save_config()
    
    def update_scanner_settings(self, **kwargs):
        """Update scanner settings and save"""
        for key, value in kwargs.items():
            self.set(f'scanner.{key}', value)
    
    def update_risk_settings(self, **kwargs):
        """Update risk management settings"""
        for key, value in kwargs.items():
            self.set(f'risk.{key}', value)
    
    def toggle_path(self, path_id: int, enabled: bool):
        """Enable/disable specific trading path"""
        enabled_paths = self.get('scanner.enabled_paths', [])
        
        if enabled and path_id not in enabled_paths:
            enabled_paths.append(path_id)
        elif not enabled and path_id in enabled_paths:
            enabled_paths.remove(path_id)
        
        self.set('scanner.enabled_paths', enabled_paths)
    
    def get_enabled_paths(self) -> List[Dict]:
        """Get list of enabled trading paths"""
        enabled_ids = self.get('scanner.enabled_paths', [1, 2, 3, 4])
        return [TradingPaths.get_path_by_id(pid) for pid in enabled_ids if TradingPaths.get_path_by_id(pid)]

class Settings:
    """Main settings class combining static and dynamic configuration"""
    
    def __init__(self):
        # Static configuration from environment
        self.WEB3_PROVIDER_URL = os.getenv('WEB3_PROVIDER_URL')
        self.CHAIN_ID = int(os.getenv('CHAIN_ID', 1))
        self.PRIVATE_KEY = os.getenv('PRIVATE_KEY')
        self.WALLET_ADDRESS = os.getenv('WALLET_ADDRESS')
        self.FLASHSWAP_CONTRACT_ADDRESS = os.getenv('FLASHSWAP_CONTRACT_ADDRESS')
        
        # Telegram configuration
        self.TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
        self.TELEGRAM_CHAT_ID = int(os.getenv('TELEGRAM_CHAT_ID', 0))
        self.TELEGRAM_ADMIN_ID = int(os.getenv('TELEGRAM_ADMIN_ID', 0))
        
        # API Keys
        self.COINGECKO_API_KEY = os.getenv('COINGECKO_API_KEY')
        self.ONEINCH_API_KEY = os.getenv('ONEINCH_API_KEY')
        
        # Database and logging
        self.DATABASE_PATH = os.getenv('DATABASE_PATH', 'data/scanner.db')
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
        self.DEVELOPMENT_MODE = os.getenv('DEVELOPMENT_MODE', 'false').lower() == 'true'
        
        # Contract addresses
        self.tokens = TokenAddresses()
        self.dexes = DexAddresses()
        self.paths = TradingPaths()
        
        # Dynamic configuration
        self.dynamic = DynamicConfig()
    
    def validate(self) -> List[str]:
        """Validate configuration and return list of missing required settings"""
        missing = []
        
        required_settings = [
            ('WEB3_PROVIDER_URL', self.WEB3_PROVIDER_URL),
            ('PRIVATE_KEY', self.PRIVATE_KEY),
            ('WALLET_ADDRESS', self.WALLET_ADDRESS),
            ('TELEGRAM_BOT_TOKEN', self.TELEGRAM_BOT_TOKEN),
            ('TELEGRAM_ADMIN_ID', self.TELEGRAM_ADMIN_ID)
        ]
        
        for name, value in required_settings:
            if not value:
                missing.append(name)
        
        return missing
    
    def get_trade_amounts(self) -> List[float]:
        """Get list of trade amounts to test (in ETH)"""
        max_size = self.dynamic.get('risk.max_trade_size', 5.0)
        return [0.1, 0.5, 1.0, 2.0, min(3.0, max_size), min(5.0, max_size)]

# Global settings instance
settings = Settings()