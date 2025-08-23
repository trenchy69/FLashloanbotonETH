# dex/price_feeds.py
import asyncio
import aiohttp
from web3 import Web3
from web3.middleware import geth_poa_middleware
from typing import Dict, List, Optional, Tuple
import json
import time
from decimal import Decimal, getcontext
from dataclasses import dataclass

from config.settings import settings
from utils.logger import log_info, log_error, log_debug, log_warning

# Set decimal precision for accurate calculations
getcontext().prec = 28

@dataclass
class PriceData:
    """Structure for price information"""
    token_a: str
    token_b: str
    price: float
    liquidity_eth: float
    dex: str
    timestamp: float
    block_number: int

@dataclass
class PairInfo:
    """DEX pair information"""
    pair_address: str
    token0: str
    token1: str
    reserves0: int
    reserves1: int
    dex: str

class Web3PriceFeeds:
    """Direct Web3 price feeds from DEX contracts"""
    
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(settings.WEB3_PROVIDER_URL))
        
        # Add middleware for PoA chains if needed
        if settings.CHAIN_ID != 1:  # Not mainnet
            self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        
        # Contract ABIs (minimal required functions)
        self.pair_abi = [
            {
                "constant": True,
                "inputs": [],
                "name": "getReserves",
                "outputs": [
                    {"internalType": "uint112", "name": "_reserve0", "type": "uint112"},
                    {"internalType": "uint112", "name": "_reserve1", "type": "uint112"},
                    {"internalType": "uint32", "name": "_blockTimestampLast", "type": "uint32"}
                ],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "token0",
                "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "token1",
                "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            }
        ]
        
        self.factory_abi = [
            {
                "constant": True,
                "inputs": [
                    {"internalType": "address", "name": "tokenA", "type": "address"},
                    {"internalType": "address", "name": "tokenB", "type": "address"}
                ],
                "name": "getPair",
                "outputs": [{"internalType": "address", "name": "pair", "type": "address"}],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            }
        ]
        
        # Initialize contracts
        self.uniswap_factory = self.w3.eth.contract(
            address=settings.dexes.UNISWAP_V2_FACTORY,
            abi=self.factory_abi
        )
        
        self.sushiswap_factory = self.w3.eth.contract(
            address=settings.dexes.SUSHISWAP_FACTORY,
            abi=self.factory_abi
        )
        
        # Cache for pair addresses
        self.pair_cache = {}
        
        log_info("Web3 price feeds initialized")
    
    def get_pair_address(self, token_a: str, token_b: str, dex: str) -> Optional[str]:
        """Get pair address for token pair on specific DEX"""
        cache_key = f"{dex}_{token_a}_{token_b}"
        
        if cache_key in self.pair_cache:
            return self.pair_cache[cache_key]
        
        try:
            factory = self.uniswap_factory if dex == "uniswap" else self.sushiswap_factory
            
            # Convert to Web3 checksum addresses
            token_a_addr = self.w3.to_checksum_address(token_a)
            token_b_addr = self.w3.to_checksum_address(token_b)
            
            pair_address = factory.functions.getPair(token_a_addr, token_b_addr).call()
            
            # Check if pair exists (not zero address)
            if pair_address == "0x0000000000000000000000000000000000000000":
                log_warning(f"No {dex} pair found for {token_a[:6]}.../{token_b[:6]}...")
                return None
            
            self.pair_cache[cache_key] = pair_address
            log_debug(f"Found {dex} pair: {pair_address}")
            return pair_address
            
        except Exception as e:
            log_error(f"Failed to get {dex} pair address", e)
            return None
    
    def get_pair_reserves(self, pair_address: str) -> Optional[Tuple[int, int, str, str]]:
        """Get reserves and token addresses for a pair"""
        try:
            pair_contract = self.w3.eth.contract(address=pair_address, abi=self.pair_abi)
            
            # Get reserves
            reserves = pair_contract.functions.getReserves().call()
            reserve0, reserve1 = reserves[0], reserves[1]
            
            # Get token addresses
            token0 = pair_contract.functions.token0().call()
            token1 = pair_contract.functions.token1().call()
            
            return reserve0, reserve1, token0, token1
            
        except Exception as e:
            log_error(f"Failed to get reserves for pair {pair_address}", e)
            return None
    
    def calculate_price(self, token_in: str, token_out: str, token0: str, token1: str, 
                       reserve0: int, reserve1: int, decimals_in: int = 18, 
                       decimals_out: int = 18) -> float:
        """Calculate price from reserves"""
        try:
            # Determine which reserve corresponds to which token
            if token_in.lower() == token0.lower():
                reserve_in = reserve0
                reserve_out = reserve1
            else:
                reserve_in = reserve1
                reserve_out = reserve0
            
            # Avoid division by zero
            if reserve_in == 0 or reserve_out == 0:
                return 0.0
            
            # Calculate price with decimal adjustments
            price_raw = Decimal(reserve_out) / Decimal(reserve_in)
            
            # Adjust for different decimals
            decimal_adjustment = Decimal(10) ** (decimals_in - decimals_out)
            price = float(price_raw * decimal_adjustment)
            
            return price
            
        except Exception as e:
            log_error("Failed to calculate price", e)
            return 0.0
    
    def get_token_decimals(self, token_address: str) -> int:
        """Get token decimals (cached for performance)"""
        # Common token decimals (to avoid extra calls)
        known_decimals = {
            settings.tokens.WETH.lower(): 18,
            settings.tokens.USDC.lower(): 6,
            settings.tokens.USDT.lower(): 6,
            settings.tokens.DAI.lower(): 18,
            settings.tokens.WBTC.lower(): 8
        }
        
        token_lower = token_address.lower()
        if token_lower in known_decimals:
            return known_decimals[token_lower]
        
        # Default to 18 if unknown
        return 18
    
    async def get_price(self, token_in: str, token_out: str, dex: str) -> Optional[PriceData]:
        """Get price for token pair on specific DEX"""
        try:
            # Get pair address
            pair_address = self.get_pair_address(token_in, token_out, dex)
            if not pair_address:
                return None
            
            # Get reserves and token info
            reserves_data = self.get_pair_reserves(pair_address)
            if not reserves_data:
                return None
            
            reserve0, reserve1, token0, token1 = reserves_data
            
            # Get token decimals
            decimals_in = self.get_token_decimals(token_in)
            decimals_out = self.get_token_decimals(token_out)
            
            # Calculate price
            price = self.calculate_price(token_in, token_out, token0, token1, 
                                       reserve0, reserve1, decimals_in, decimals_out)
            
            # Estimate liquidity in ETH (rough estimate)
            weth_address = settings.tokens.WETH.lower()
            if token0.lower() == weth_address:
                liquidity_eth = reserve0 / (10 ** 18)
            elif token1.lower() == weth_address:
                liquidity_eth = reserve1 / (10 ** 18)
            else:
                # Rough estimate if no WETH in pair
                liquidity_eth = max(reserve0, reserve1) / (10 ** 18) * 0.5
            
            # Get current block
            current_block = self.w3.eth.block_number
            
            return PriceData(
                token_a=token_in,
                token_b=token_out,
                price=price,
                liquidity_eth=liquidity_eth,
                dex=dex,
                timestamp=time.time(),
                block_number=current_block
            )
            
        except Exception as e:
            log_error(f"Failed to get {dex} price for {token_in[:6]}.../{token_out[:6]}...", e)
            return None

class DexPriceManager:
    """Manager for all DEX price feeds"""
    
    def __init__(self):
        self.web3_feeds = Web3PriceFeeds()
        self.price_cache = {}
        self.cache_duration = 10  # Cache prices for 10 seconds
        
    async def get_all_prices_for_path(self, path_info: Dict) -> Dict[str, PriceData]:
        """Get prices from all DEXs for a trading path"""
        token_a = getattr(settings.tokens, path_info['tokens'][0])
        token_b = getattr(settings.tokens, path_info['tokens'][1])
        
        prices = {}
        
        # Get Uniswap price (WETH -> Token)
        uniswap_price = await self.web3_feeds.get_price(token_a, token_b, "uniswap")
        if uniswap_price:
            prices['uniswap'] = uniswap_price
        
        # Get Sushiswap price (Token -> WETH)
        sushiswap_price = await self.web3_feeds.get_price(token_b, token_a, "sushiswap")
        if sushiswap_price:
            prices['sushiswap'] = sushiswap_price
        
        return prices
    
    async def get_all_path_prices(self) -> Dict[int, Dict[str, PriceData]]:
        """Get prices for all enabled trading paths"""
        all_prices = {}
        enabled_paths = settings.dynamic.get_enabled_paths()
        
        for path in enabled_paths:
            path_id = path['id']
            log_debug(f"Fetching prices for path {path_id}: {path['name']}")
            
            try:
                path_prices = await self.get_all_prices_for_path(path)
                if path_prices:
                    all_prices[path_id] = path_prices
                    log_debug(f"Got {len(path_prices)} prices for path {path_id}")
                else:
                    log_warning(f"No prices available for path {path_id}")
                    
            except Exception as e:
                log_error(f"Failed to get prices for path {path_id}", e)
        
        return all_prices
    
    async def test_price_feeds(self) -> bool:
        """Test if price feeds are working correctly"""
        log_info("Testing price feeds...")
        
        try:
            # Test with WETH/USDC pair
            uniswap_price = await self.web3_feeds.get_price(
                settings.tokens.WETH, 
                settings.tokens.USDC, 
                "uniswap"
            )
            
            sushiswap_price = await self.web3_feeds.get_price(
                settings.tokens.WETH, 
                settings.tokens.USDC, 
                "sushiswap"
            )
            
            if uniswap_price and sushiswap_price:
                log_info(f"✅ Price feeds working!")
                log_info(f"Uniswap WETH/USDC: {uniswap_price.price:.2f}")
                log_info(f"Sushiswap WETH/USDC: {sushiswap_price.price:.2f}")
                
                price_diff = abs(uniswap_price.price - sushiswap_price.price)
                price_diff_percent = (price_diff / uniswap_price.price) * 100
                log_info(f"Price difference: {price_diff_percent:.3f}%")
                
                return True
            else:
                log_error("❌ Price feeds not working - no price data returned")
                return False
                
        except Exception as e:
            log_error("❌ Price feeds test failed", e)
            return False

# Global price manager instance
price_manager = DexPriceManager()