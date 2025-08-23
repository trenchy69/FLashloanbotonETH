import asyncio
import time
from typing import Dict, List, Optional, Tuple
from web3 import Web3
from config.settings import settings
from utils.logger import logger

class PriceFeed:
    def __init__(self, web3_instance):
        self.w3 = web3_instance
        self.cache = {}
        self.cache_ttl = 30  # 30 seconds cache
        
        # Factory contract ABIs
        self.factory_abi = [
            {
                "constant": True,
                "inputs": [
                    {"name": "", "type": "address"},
                    {"name": "", "type": "address"}
                ],
                "name": "getPair",
                "outputs": [{"name": "", "type": "address"}],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            }
        ]
        
        # Pair contract ABI for reserves
        self.pair_abi = [
            {
                "constant": True,
                "inputs": [],
                "name": "getReserves",
                "outputs": [
                    {"name": "_reserve0", "type": "uint112"},
                    {"name": "_reserve1", "type": "uint112"},
                    {"name": "_blockTimestampLast", "type": "uint32"}
                ],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "token0",
                "outputs": [{"name": "", "type": "address"}],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "token1",
                "outputs": [{"name": "", "type": "address"}],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            }
        ]
        
        # Initialize factory contracts
        try:
            self.uniswap_factory = self.w3.eth.contract(
                address=Web3.to_checksum_address(settings.UNISWAP_V2_FACTORY),
                abi=self.factory_abi
            )
            self.sushiswap_factory = self.w3.eth.contract(
                address=Web3.to_checksum_address(settings.SUSHISWAP_FACTORY),
                abi=self.factory_abi
            )
            logger.info("✅ DEX factory contracts initialized")
        except Exception as e:
            logger.error(f"❌ Error initializing factory contracts: {e}")
    
    def _get_cache_key(self, *args) -> str:
        """Generate cache key from arguments"""
        return "_".join(str(arg) for arg in args)
    
    def _is_cache_valid(self, key: str) -> bool:
        """Check if cached data is still valid"""
        if key not in self.cache:
            return False
        return time.time() - self.cache[key]['timestamp'] < self.cache_ttl
    
    def _get_from_cache(self, key: str):
        """Get data from cache if valid"""
        if self._is_cache_valid(key):
            return self.cache[key]['data']
        return None
    
    def _set_cache(self, key: str, data):
        """Set data in cache"""
        self.cache[key] = {
            'data': data,
            'timestamp': time.time()
        }
    
    async def get_pair_address(self, dex: str, token_a: str, token_b: str) -> Optional[str]:
        """Get pair address for given tokens on specified DEX"""
        cache_key = self._get_cache_key("pair", dex, token_a, token_b)
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached
        
        try:
            # Convert to checksum addresses
            token_a = Web3.to_checksum_address(token_a)
            token_b = Web3.to_checksum_address(token_b)
            
            # Get appropriate factory
            if dex.lower() == 'uniswap':
                factory = self.uniswap_factory
            elif dex.lower() == 'sushiswap':
                factory = self.sushiswap_factory
            else:
                raise ValueError(f"Unsupported DEX: {dex}")
            
            # Get pair address
            pair_address = factory.functions.getPair(token_a, token_b).call()
            
            # Check if pair exists (non-zero address)
            if pair_address == "0x0000000000000000000000000000000000000000":
                return None
            
            self._set_cache(cache_key, pair_address)
            return pair_address
            
        except Exception as e:
            logger.debug(f"Error getting pair address for {dex} {token_a}/{token_b}: {e}")
            return None
    
    async def get_reserves(self, pair_address: str, token_a: str, token_b: str) -> Optional[Dict]:
        """Get reserves and calculate price for a pair"""
        cache_key = self._get_cache_key("reserves", pair_address)
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached
        
        try:
            pair_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(pair_address),
                abi=self.pair_abi
            )
            
            # Get reserves
            reserves = pair_contract.functions.getReserves().call()
            reserve0, reserve1, _ = reserves
            
            # Get token order
            token0 = pair_contract.functions.token0().call()
            token1 = pair_contract.functions.token1().call()
            
            # Convert to checksum addresses for comparison
            token_a = Web3.to_checksum_address(token_a)
            token_b = Web3.to_checksum_address(token_b)
            token0 = Web3.to_checksum_address(token0)
            token1 = Web3.to_checksum_address(token1)
            
            # Determine which reserve belongs to which token
            if token_a == token0:
                reserve_a, reserve_b = reserve0, reserve1
            elif token_a == token1:
                reserve_a, reserve_b = reserve1, reserve0
            else:
                logger.error(f"Token mismatch in pair {pair_address}: {token_a} not found")
                return None
            
            # Calculate price (token_b per token_a)
            if reserve_a > 0:
                price = reserve_b / reserve_a
            else:
                return None
            
            result = {
                'pair_address': pair_address,
                'reserve0': reserve0,
                'reserve1': reserve1,
                'reserve_a': reserve_a,  # Reserve of token_a
                'reserve_b': reserve_b,  # Reserve of token_b
                'price': price,          # Price of token_a in terms of token_b
                'token0': token0,
                'token1': token1,
                'liquidity_eth': await self._estimate_liquidity_eth(reserve_a, reserve_b, token_a, token_b)
            }
            
            self._set_cache(cache_key, result)
            return result
            
        except Exception as e:
            logger.debug(f"Error getting reserves for pair {pair_address}: {e}")
            return None
    
    async def _estimate_liquidity_eth(self, reserve_a: int, reserve_b: int, token_a: str, token_b: str) -> float:
        """Estimate total liquidity in ETH terms"""
        try:
            # Get token symbols for estimation
            weth_address = settings.get_token_address('WETH').lower()
            
            if token_a.lower() == weth_address:
                return float(Web3.from_wei(reserve_a * 2, 'ether'))  # Double for total liquidity
            elif token_b.lower() == weth_address:
                return float(Web3.from_wei(reserve_b * 2, 'ether'))  # Double for total liquidity
            
            # Rough estimates for major tokens (in ETH terms)
            token_eth_values = {
                settings.get_token_address('USDC').lower(): 0.0003,
                settings.get_token_address('USDT').lower(): 0.0003,
                settings.get_token_address('DAI').lower(): 0.0003,
                settings.get_token_address('WBTC').lower(): 15.0,
            }
            
            # Try to estimate using token_a
            eth_value = token_eth_values.get(token_a.lower(), 1.0)
            return float(Web3.from_wei(reserve_a * 2, 'ether')) * eth_value
            
        except Exception:
            return 0.0
    
    async def get_prices_for_pair(self, token_a: str, token_b: str) -> Dict[str, Optional[Dict]]:
        """Get prices from both Uniswap and Sushiswap for a token pair"""
        results = {
            'uniswap': None,
            'sushiswap': None,
            'token_a': token_a,
            'token_b': token_b
        }
        
        try:
            # Get prices from both DEXs concurrently
            uniswap_task = self._get_dex_price('uniswap', token_a, token_b)
            sushiswap_task = self._get_dex_price('sushiswap', token_a, token_b)
            
            uniswap_result, sushiswap_result = await asyncio.gather(
                uniswap_task, sushiswap_task, return_exceptions=True
            )
            
            if not isinstance(uniswap_result, Exception):
                results['uniswap'] = uniswap_result
            
            if not isinstance(sushiswap_result, Exception):
                results['sushiswap'] = sushiswap_result
            
            return results
            
        except Exception as e:
            logger.error(f"Error getting prices for {token_a}/{token_b}: {e}")
            return results
    
    async def _get_dex_price(self, dex: str, token_a: str, token_b: str) -> Optional[Dict]:
        """Get price from specific DEX"""
        try:
            # Get pair address
            pair_address = await self.get_pair_address(dex, token_a, token_b)
            if not pair_address:
                return None
            
            # Get reserves and price
            reserves_data = await self.get_reserves(pair_address, token_a, token_b)
            if not reserves_data:
                return None
            
            return {
                'dex': dex,
                'pair_address': pair_address,
                'price': reserves_data['price'],
                'reserve_a': reserves_data['reserve_a'],
                'reserve_b': reserves_data['reserve_b'],
                'liquidity_eth': reserves_data['liquidity_eth'],
                'timestamp': time.time()
            }
            
        except Exception as e:
            logger.debug(f"Error getting {dex} price for {token_a}/{token_b}: {e}")
            return None
    
    async def get_multiple_prices(self, pairs: List[Dict]) -> List[Dict]:
        """Get prices for multiple pairs efficiently"""
        tasks = []
        
        for pair in pairs:
            token_a = pair['token1']['address']
            token_b = pair['token2']['address']
            task = self.get_prices_for_pair(token_a, token_b)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error getting prices for pair {i}: {result}")
                processed_results.append(None)
            else:
                processed_results.append(result)
        
        return processed_results
    
    def calculate_price_impact(self, reserves: Dict, trade_amount: int, is_token_a: bool = True) -> float:
        """Calculate price impact for a trade"""
        try:
            if is_token_a:
                # Selling token_a for token_b
                reserve_in = reserves['reserve_a']
                reserve_out = reserves['reserve_b']
            else:
                # Selling token_b for token_a
                reserve_in = reserves['reserve_b']
                reserve_out = reserves['reserve_a']
            
            # Constant product formula with 0.3% fee
            amount_in_with_fee = trade_amount * 997
            numerator = amount_in_with_fee * reserve_out
            denominator = (reserve_in * 1000) + amount_in_with_fee
            amount_out = numerator // denominator
            
            # Calculate price impact
            original_price = reserve_out / reserve_in
            new_price = (reserve_out - amount_out) / (reserve_in + trade_amount)
            
            price_impact = abs(new_price - original_price) / original_price
            return price_impact
            
        except Exception as e:
            logger.error(f"Error calculating price impact: {e}")
            return 1.0  # Return high impact on error
    
    def get_optimal_trade_amount(self, uniswap_reserves: Dict, sushiswap_reserves: Dict, max_amount_wei: int) -> int:
        """Calculate optimal trade amount considering price impact"""
        try:
            # Test different amounts to find optimal
            amounts_to_test = [
                max_amount_wei // 10,    # 10%
                max_amount_wei // 5,     # 20%
                max_amount_wei // 2,     # 50%
                max_amount_wei,          # 100%
            ]
            
            best_profit = 0
            best_amount = amounts_to_test[0]
            
            for amount in amounts_to_test:
                # Calculate price impact on both DEXs
                uni_impact = self.calculate_price_impact(uniswap_reserves, amount)
                sushi_impact = self.calculate_price_impact(sushiswap_reserves, amount)
                
                # Skip if price impact is too high
                if uni_impact > 0.03 or sushi_impact > 0.03:  # 3% max impact
                    continue
                
                # Estimate profit (simplified)
                price_diff = abs(uniswap_reserves['price'] - sushiswap_reserves['price'])
                estimated_profit = amount * price_diff * (1 - uni_impact - sushi_impact)
                
                if estimated_profit > best_profit:
                    best_profit = estimated_profit
                    best_amount = amount
            
            return best_amount
            
        except Exception as e:
            logger.error(f"Error calculating optimal trade amount: {e}")
            return max_amount_wei // 10  # Conservative fallback
    
    async def test_price_feeds(self) -> Dict:
        """Test price feeds with sample pairs"""
        logger.info("🧪 Testing price feeds...")
        
        test_results = {
            'total_tests': 0,
            'successful_tests': 0,
            'failed_tests': 0,
            'test_details': []
        }
        
        # Test with high-priority pairs
        test_pairs = [
            ('WETH', 'USDC'),
            ('WETH', 'USDT'), 
            ('WETH', 'DAI'),
            ('USDC', 'USDT')
        ]
        
        for token_a_symbol, token_b_symbol in test_pairs:
            test_results['total_tests'] += 1
            
            try:
                token_a = settings.get_token_address(token_a_symbol)
                token_b = settings.get_token_address(token_b_symbol)
                
                if not token_a or not token_b:
                    test_results['failed_tests'] += 1
                    continue
                
                # Get prices
                prices = await self.get_prices_for_pair(token_a, token_b)
                
                # Check results
                has_uniswap = prices['uniswap'] is not None
                has_sushiswap = prices['sushiswap'] is not None
                
                test_detail = {
                    'pair': f"{token_a_symbol}/{token_b_symbol}",
                    'uniswap_available': has_uniswap,
                    'sushiswap_available': has_sushiswap,
                    'both_available': has_uniswap and has_sushiswap
                }
                
                if has_uniswap and has_sushiswap:
                    price_diff = abs(prices['uniswap']['price'] - prices['sushiswap']['price'])
                    price_diff_pct = (price_diff / min(prices['uniswap']['price'], prices['sushiswap']['price'])) * 100
                    test_detail['price_difference_pct'] = price_diff_pct
                    test_detail['uniswap_liquidity_eth'] = prices['uniswap']['liquidity_eth']
                    test_detail['sushiswap_liquidity_eth'] = prices['sushiswap']['liquidity_eth']
                
                test_results['test_details'].append(test_detail)
                
                if has_uniswap or has_sushiswap:
                    test_results['successful_tests'] += 1
                else:
                    test_results['failed_tests'] += 1
                
                logger.info(f"  {token_a_symbol}/{token_b_symbol}: Uni={has_uniswap}, Sushi={has_sushiswap}")
                
            except Exception as e:
                test_results['failed_tests'] += 1
                logger.error(f"  {token_a_symbol}/{token_b_symbol}: Error - {e}")
        
        success_rate = (test_results['successful_tests'] / test_results['total_tests']) * 100
        logger.info(f"✅ Price feed test complete: {success_rate:.1f}% success rate")
        
        return test_results