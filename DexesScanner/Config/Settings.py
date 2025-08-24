import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Settings:
    def __init__(self):
        # Network Configuration
        self.WEB3_PROVIDER_URL = os.getenv('WEB3_PROVIDER_URL')
        self.CHAIN_ID = int(os.getenv('CHAIN_ID', 1))
        
        # Development Settings
        self.DEVELOPMENT_MODE = os.getenv('DEVELOPMENT_MODE', 'true').lower() == 'true'
        self.TESTNET_PROVIDER_URL = os.getenv('TESTNET_PROVIDER_URL')
        
        # Trading Parameters
        self.MIN_PROFIT_ETH = float(os.getenv('MIN_PROFIT_ETH', 0.01))
        self.MAX_GAS_PRICE_GWEI = int(os.getenv('MAX_GAS_PRICE', 50))  # Fixed: was MAX_GAS_PRICE_GWEI
        self.SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL', 10))
        
        # Auto-Discovery Configuration
        self.AUTO_DISCOVERY_ENABLED = os.getenv('AUTO_DISCOVERY_ENABLED', 'true').lower() == 'true'
        self.MIN_LIQUIDITY_ETH = float(os.getenv('MIN_LIQUIDITY_ETH', 10.0))  # Minimum liquidity per DEX
        self.MAX_PAIRS_TO_SCAN = int(os.getenv('MAX_PAIRS_TO_SCAN', 100))
        self.DISCOVERY_INTERVAL_HOURS = int(os.getenv('DISCOVERY_INTERVAL_HOURS', 24))
        
        # DEX Contract Addresses
        self.UNISWAP_V2_FACTORY = '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f'
        self.UNISWAP_V2_ROUTER = '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D'
        self.SUSHISWAP_FACTORY = '0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac'
        self.SUSHISWAP_ROUTER = '0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F'
        
        # Token Universe for Auto-Discovery
        self.TOKEN_UNIVERSE = {
            # Stablecoins (High Priority)
            'USDC': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
            'USDT': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'DAI': '0x6B175474E89094C44Da98b954EedeAC495271d0F',
            'FRAX': '0x853d955aCEf822Db058eb8505911ED77F175b99e',
            'BUSD': '0x4Fabb145d64652a948d72533023f6E7A623C7C53',
            
            # Major Tokens (High Priority)
            'WETH': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
            'WBTC': '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',
            'ETH': '0x0000000000000000000000000000000000000000',  # Native ETH
            
            # DeFi Blue Chips (Medium Priority)
            'UNI': '0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984',
            'LINK': '0x514910771AF9Ca656af840dff83E8264EcF986CA',
            'AAVE': '0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9',
            'COMP': '0xc00e94Cb662C3520282E6f5717214004A7f26888',
            'MKR': '0x9f8F72aA9304c8B593d555F12eF6589CC3A579A2',
            'SNX': '0xC011a73ee8576Fb46F5E1c5751cA3B9Fe0af2a6F',
            'CRV': '0xD533a949740bb3306d119CC777fa900bA034cd52',
            'SUSHI': '0x6B3595068778DD592e39A122f4f5a5cF09C90fE2',
            'YFI': '0x0bc529c00C6401aEF6D220BE8C6Ea1667F6Ad93e',
            
            # Layer 2 & Infrastructure (Medium Priority)
            'MATIC': '0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0',
            'LDO': '0x5A98FcBEA516Cf06857215779Fd812CA3beF1B32',
            'RPL': '0xD33526068D116cE69F19A9ee46F0bd304F21A51f',
            
            # Meme/Community (Low Priority - High Volatility)
            'SHIB': '0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE',
            'DOGE': '0x4206931337dc273a630d328dA6441786BfaD668f',
            'PEPE': '0x6982508145454Ce325dDbE47a25d4ec3d2311933',
            
            # Gaming/NFT (Medium Priority)
            'APE': '0x4d224452801ACEd8B2F0aebE155379bb5D594381',
            'SAND': '0x3845badAde8e6dFF049820680d1F14bD3903a5d0',
            'MANA': '0x0F5D2fB29fb7d3CFeE444a200298f468908cC942',
        }
        
        # Priority groupings for scanning efficiency
        self.PRIORITY_GROUPS = {
            'high': ['WETH', 'USDC', 'USDT', 'DAI', 'WBTC', 'ETH'],
            'medium': ['UNI', 'LINK', 'AAVE', 'COMP', 'MKR', 'MATIC', 'LDO'],
            'low': ['SHIB', 'DOGE', 'PEPE', 'APE', 'SAND', 'MANA']
        }
        
        # Pair Generation Rules
        self.PAIR_RULES = {
            'always_include_weth': True,  # WETH pairs have highest liquidity
            'stablecoin_pairs': True,     # Stablecoin arbitrage opportunities
            'major_token_pairs': True,    # Blue chip token combinations
            'exclude_low_liquidity': True, # Skip pairs with <10 ETH liquidity
            'max_pairs_per_token': 10,    # Limit combinations per token
        }
        
        # Discovery Settings
        self.DISCOVERY_SETTINGS = {
            'batch_size': 20,             # Check 20 pairs at once
            'liquidity_threshold_eth': self.MIN_LIQUIDITY_ETH,
            'volume_24h_threshold_eth': 50.0,  # Minimum 24h volume
            'price_deviation_max': 0.1,   # Skip pairs with >10% price deviation (likely broken)
            'update_interval_seconds': 3600,  # Update pair list hourly
        }
        
        # Risk Management for Auto-Discovery
        self.RISK_SETTINGS = {
            'max_trade_amount_eth': 5.0,  # Conservative limit for unknown pairs
            'confidence_threshold': 0.7,  # Higher confidence required for auto-discovered pairs
            'blacklist_tokens': [],       # Tokens to never trade (scam tokens, etc.)
            'require_both_dexs': True,    # Pair must exist on both Uniswap and Sushiswap
        }
        
        # Communication
        self.TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
        self.TELEGRAM_ADMIN_ID = os.getenv('TELEGRAM_ADMIN_ID')
        
        # Contract addresses (for execution later)
        self.PRIVATE_KEY = os.getenv('PRIVATE_KEY')
        self.WALLET_ADDRESS = os.getenv('WALLET_ADDRESS')
        self.FLASHSWAP_CONTRACT_ADDRESS = os.getenv('FLASHSWAP_CONTRACT_ADDRESS')
        
        # Configuration file paths
        self.config_dir = Path(__file__).parent
        self.user_config_path = self.config_dir / 'user_config.json'
        self.discovered_pairs_path = self.config_dir / 'discovered_pairs.json'
        
        # Load user configuration
        self.load_user_config()
        
    def load_user_config(self):
        """Load user-specific settings"""
        if self.user_config_path.exists():
            try:
                with open(self.user_config_path, 'r') as f:
                    user_config = json.load(f)
                    # Override default settings with user preferences
                    for key, value in user_config.items():
                        if hasattr(self, key):
                            setattr(self, key, value)
            except Exception as e:
                print(f"Error loading user config: {e}")
    
    def save_user_config(self):
        """Save current settings to user config file"""
        config_data = {
            'MIN_PROFIT_ETH': self.MIN_PROFIT_ETH,
            'MAX_GAS_PRICE_GWEI': self.MAX_GAS_PRICE_GWEI,
            'SCAN_INTERVAL': self.SCAN_INTERVAL,
            'MIN_LIQUIDITY_ETH': self.MIN_LIQUIDITY_ETH,
            'MAX_PAIRS_TO_SCAN': self.MAX_PAIRS_TO_SCAN,
            'AUTO_DISCOVERY_ENABLED': self.AUTO_DISCOVERY_ENABLED
        }
        
        try:
            with open(self.user_config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
        except Exception as e:
            print(f"Error saving user config: {e}")
    
    def update_setting(self, key: str, value):
        """Update a setting and save to config"""
        if hasattr(self, key):
            # Type conversion based on existing value type
            current_val = getattr(self, key)
            if isinstance(current_val, bool):
                value = str(value).lower() in ['true', '1', 'yes', 'on']
            elif isinstance(current_val, int):
                value = int(value)
            elif isinstance(current_val, float):
                value = float(value)
            
            setattr(self, key, value)
            self.save_user_config()
            return True
        return False
    
    def get_token_address(self, symbol: str) -> str:
        """Get token address by symbol"""
        return self.TOKEN_UNIVERSE.get(symbol.upper())
    
    def get_priority_tokens(self, priority: str = 'high') -> list:
        """Get tokens by priority level"""
        return self.PRIORITY_GROUPS.get(priority, [])
    
    def is_valid_token(self, symbol: str) -> bool:
        """Check if token is in our universe"""
        return symbol.upper() in self.TOKEN_UNIVERSE

# Global settings instance
settings = Settings()