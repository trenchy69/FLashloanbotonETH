import asyncio
import json
import time
from typing import Dict, List, Tuple, Optional
from itertools import combinations
from web3 import Web3
from config.settings import settings
from utils.logger import logger
from dex.price_feeds import PriceFeed

class PairDiscovery:
    def __init__(self, web3_instance):
        self.w3 = web3_instance
        self.price_feed = PriceFeed(web3_instance)
        self.discovered_pairs = []
        self.last_discovery_time = 0
        self.pair_cache = {}
        
        # Load existing discovered pairs
        self.load_discovered_pairs()
        
    def load_discovered_pairs(self):
        """Load previously discovered pairs from file"""
        try:
            if settings.discovered_pairs_path.exists():
                with open(settings.discovered_pairs_path, 'r') as f:
                    data = json.load(f)
                    self.discovered_pairs = data.get('pairs', [])
                    self.last_discovery_time = data.get('last_update', 0)
                    logger.info(f"Loaded {len(self.discovered_pairs)} previously discovered pairs")
        except Exception as e:
            logger.error(f"Error loading discovered pairs: {e}")
            self.discovered_pairs = []
    
    def save_discovered_pairs(self):
        """Save discovered pairs to file"""
        try:
            data = {
                'pairs': self.discovered_pairs,
                'last_update': int(time.time()),
                'discovery_settings': {
                    'min_liquidity_eth': settings.MIN_LIQUIDITY_ETH,
                    'max_pairs': settings.MAX_PAIRS_TO_SCAN
                }
            }
            
            settings.config_dir.mkdir(exist_ok=True)
            with open(settings.discovered_pairs_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(self.discovered_pairs)} discovered pairs")
        except Exception as e:
            logger.error(f"Error saving discovered pairs: {e}")
    
    async def discover_all_pairs(self, force_refresh: bool = False) -> List[Dict]:
        """Main discovery function - find all profitable trading pairs"""
        current_time = time.time()
        time_since_last = current_time - self.last_discovery_time
        
        # Check if we need to refresh
        if not force_refresh and time_since_last < (settings.DISCOVERY_INTERVAL_HOURS * 3600):
            if self.discovered_pairs:
                logger.info(f"Using cached pairs. Next discovery in {((settings.DISCOVERY_INTERVAL_HOURS * 3600) - time_since_last) / 3600:.1f} hours")
                return self.discovered_pairs
        
        logger.info("🔍 Starting pair discovery process...")
        
        # Generate potential pairs
        potential_pairs = self.generate_potential_pairs()
        logger.info(f"Generated {len(potential_pairs)} potential pairs to check")
        
        # Check pairs in batches
        valid_pairs = []
        batch_size = settings.DISCOVERY_SETTINGS['batch_size']
        
        for i in range(0, len(potential_pairs), batch_size):
            batch = potential_pairs[i:i + batch_size]
            logger.info(f"Checking batch {i//batch_size + 1}/{(len(potential_pairs) + batch_size - 1)//batch_size}")
            
            batch_results = await self.check_pair_batch(batch)
            valid_pairs.extend(batch_results)
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(1)
        
        # Sort by liquidity and profitability potential
        valid_pairs = self.rank_pairs(valid_pairs)
        
        # Limit to max pairs
        if len(valid_pairs) > settings.MAX_PAIRS_TO_SCAN:
            valid_pairs = valid_pairs[:settings.MAX_PAIRS_TO_SCAN]
            logger.info(f"Limited to top {settings.MAX_PAIRS_TO_SCAN} pairs by liquidity")
        
        self.discovered_pairs = valid_pairs
        self.last_discovery_time = current_time
        self.save_discovered_pairs()
        
        logger.info(f"✅ Discovery complete! Found {len(valid_pairs)} valid pairs")
        return valid_pairs
    
    def generate_potential_pairs(self) -> List[Tuple[str, str]]:
        """Generate all potential trading pairs based on rules"""
        pairs = []
        tokens = list(settings.TOKEN_UNIVERSE.keys())
        
        # Priority-based pair generation
        for priority in ['high', 'medium', 'low']:
            priority_tokens = settings.get_priority_tokens(priority)
            
            if settings.PAIR_RULES['always_include_weth'] and 'WETH' in tokens:
                # WETH pairs (highest liquidity)
                for token in priority_tokens:
                    if token != 'WETH':
                        pairs.append(('WETH', token))
            
            # Stablecoin pairs
            if settings.PAIR_RULES['stablecoin_pairs']:
                stablecoins = ['USDC', 'USDT', 'DAI', 'FRAX']
                for stable1, stable2 in combinations([s for s in stablecoins if s in priority_tokens], 2):
                    pairs.append((stable1, stable2))
            
            # Major token combinations within priority group
            if settings.PAIR_RULES['major_token_pairs']:
                for token1, token2 in combinations(priority_tokens, 2):
                    if token1 != token2 and (token1, token2) not in pairs and (token2, token1) not in pairs:
                        pairs.append((token1, token2))
        
        # Remove duplicates and apply limits
        unique_pairs = []
        token_pair_count = {}
        
        for token1, token2 in pairs:
            # Count pairs per token
            for token in [token1, token2]:
                if token not in token_pair_count:
                    token_pair_count[token] = 0
            
            # Check limits
            if (token_pair_count[token1] < settings.PAIR_RULES['max_pairs_per_token'] and
                token_pair_count[token2] < settings.PAIR_RULES['max_pairs_per_token']):
                unique_pairs.append((token1, token2))
                token_pair_count[token1] += 1
                token_pair_count[token2] += 1
        
        return unique_pairs
    
    async def check_pair_batch(self, pairs: List[Tuple[str, str]]) -> List[Dict]:
        """Check a batch of pairs for validity and liquidity"""
        valid_pairs = []
        
        for token1_symbol, token2_symbol in pairs:
            try:
                pair_info = await self.check_single_pair(token1_symbol, token2_symbol)
                if pair_info:
                    valid_pairs.append(pair_info)
                    
            except Exception as e:
                logger.debug(f"Error checking pair {token1_symbol}/{token2_symbol}: {e}")
                continue
        
        return valid_pairs
    
    async def check_single_pair(self, token1_symbol: str, token2_symbol: str) -> Optional[Dict]:
        """Check if a single pair meets our criteria"""
        token1_address = settings.get_token_address(token1_symbol)
        token2_address = settings.get_token_address(token2_symbol)
        
        if not token1_address or not token2_address:
            return None
        
        try:
            # Check if pair exists on both DEXs
            uniswap_pair = await self.price_feed.get_pair_address('uniswap', token1_address, token2_address)
            sushiswap_pair = await self.price_feed.get_pair_address('sushiswap', token1_address, token2_address)
            
            if not uniswap_pair or not sushiswap_pair:
                return None
            
            # Get liquidity data
            uniswap_data = await self.price_feed.get_reserves(uniswap_pair, token1_address, token2_address)
            sushiswap_data = await self.price_feed.get_reserves(sushiswap_pair, token1_address, token2_address)
            
            if not uniswap_data or not sushiswap_data:
                return None
            
            # Calculate liquidity in ETH terms
            uniswap_liquidity_eth = await self.calculate_liquidity_eth(uniswap_data, token1_symbol, token2_symbol)
            sushiswap_liquidity_eth = await self.calculate_liquidity_eth(sushiswap_data, token1_symbol, token2_symbol)
            
            # Check minimum liquidity requirement
            min_liquidity = settings.DISCOVERY_SETTINGS['liquidity_threshold_eth']
            if uniswap_liquidity_eth < min_liquidity or sushiswap_liquidity_eth < min_liquidity:
                return None
            
            # Calculate current price difference
            price_diff = abs(uniswap_data['price'] - sushiswap_data['price']) / min(uniswap_data['price'], sushiswap_data['price'])
            
            # Skip pairs with extreme price differences (likely broken)
            if price_diff > settings.DISCOVERY_SETTINGS['price_deviation_max']:
                return None
            
            # Create pair info
            pair_info = {
                'token1': {
                    'symbol': token1_symbol,
                    'address': token1_address
                },
                'token2': {
                    'symbol': token2_symbol,
                    'address': token2_address
                },
                'uniswap': {
                    'pair_address': uniswap_pair,
                    'liquidity_eth': uniswap_liquidity_eth,
                    'price': uniswap_data['price']
                },
                'sushiswap': {
                    'pair_address': sushiswap_pair,
                    'liquidity_eth': sushiswap_liquidity_eth,
                    'price': sushiswap_data['price']
                },
                'metrics': {
                    'price_difference_pct': price_diff * 100,
                    'min_liquidity_eth': min(uniswap_liquidity_eth, sushiswap_liquidity_eth),
                    'total_liquidity_eth': uniswap_liquidity_eth + sushiswap_liquidity_eth,
                    'liquidity_ratio': min(uniswap_liquidity_eth, sushiswap_liquidity_eth) / max(uniswap_liquidity_eth, sushiswap_liquidity_eth)
                },
                'priority': self.get_pair_priority(token1_symbol, token2_symbol),
                'last_checked': int(time.time())
            }
            
            logger.debug(f"✅ Valid pair: {token1_symbol}/{token2_symbol} - Liquidity: {pair_info['metrics']['total_liquidity_eth']:.2f} ETH")
            return pair_info
            
        except Exception as e:
            logger.debug(f"Error validating pair {token1_symbol}/{token2_symbol}: {e}")
            return None
    
    async def calculate_liquidity_eth(self, reserves_data: Dict, token1_symbol: str, token2_symbol: str) -> float:
        """Calculate total liquidity in ETH terms"""
        try:
            # If one token is WETH, use its reserve directly
            if token1_symbol == 'WETH':
                return float(Web3.from_wei(reserves_data['reserve0'], 'ether'))
            elif token2_symbol == 'WETH':
                return float(Web3.from_wei(reserves_data['reserve1'], 'ether'))
            
            # For non-WETH pairs, estimate ETH value
            # This is a simplified calculation - in production you'd want more accurate price feeds
            eth_price_estimates = {
                'USDC': 0.0003,  # Approximate ETH price in terms of token
                'USDT': 0.0003,
                'DAI': 0.0003,
                'WBTC': 15.0,    # WBTC is worth ~15 ETH
            }
            
            # Use token1 reserve for estimation
            token1_reserve = float(Web3.from_wei(reserves_data['reserve0'], 'ether'))
            eth_multiplier = eth_price_estimates.get(token1_symbol, 1.0)
            
            return token1_reserve * eth_multiplier
            
        except Exception as e:
            logger.debug(f"Error calculating liquidity for {token1_symbol}/{token2_symbol}: {e}")
            return 0.0
    
    def get_pair_priority(self, token1_symbol: str, token2_symbol: str) -> str:
        """Determine priority level for a pair"""
        high_priority = settings.get_priority_tokens('high')
        medium_priority = settings.get_priority_tokens('medium')
        
        if token1_symbol in high_priority and token2_symbol in high_priority:
            return 'high'
        elif token1_symbol in high_priority or token2_symbol in high_priority:
            return 'medium'
        elif token1_symbol in medium_priority and token2_symbol in medium_priority:
            return 'medium'
        else:
            return 'low'
    
    def rank_pairs(self, pairs: List[Dict]) -> List[Dict]:
        """Rank pairs by profitability potential"""
        def calculate_score(pair):
            # Scoring factors
            liquidity_score = min(pair['metrics']['total_liquidity_eth'] / 100, 10)  # Max 10 points for liquidity
            price_diff_score = pair['metrics']['price_difference_pct'] * 10  # Reward price differences
            priority_score = {'high': 10, 'medium': 5, 'low': 1}[pair['priority']]
            liquidity_balance_score = pair['metrics']['liquidity_ratio'] * 5  # Reward balanced liquidity
            
            return liquidity_score + price_diff_score + priority_score + liquidity_balance_score
        
        # Sort by score descending
        pairs.sort(key=calculate_score, reverse=True)
        
        # Add rank to each pair
        for i, pair in enumerate(pairs):
            pair['rank'] = i + 1
            pair['score'] = calculate_score(pair)
        
        return pairs
    
    def get_active_pairs(self) -> List[Dict]:
        """Get currently active pairs for scanning"""
        if not self.discovered_pairs:
            logger.warning("No discovered pairs available. Run discovery first.")
            return []
        
        # Filter out stale pairs (older than 24 hours)
        current_time = int(time.time())
        fresh_pairs = []
        
        for pair in self.discovered_pairs:
            age_hours = (current_time - pair.get('last_checked', 0)) / 3600
            if age_hours < 24:  # Pair data is less than 24 hours old
                fresh_pairs.append(pair)
        
        return fresh_pairs
    
    def get_pair_info(self, token1_symbol: str, token2_symbol: str) -> Optional[Dict]:
        """Get info for a specific pair"""
        for pair in self.discovered_pairs:
            if ((pair['token1']['symbol'] == token1_symbol and pair['token2']['symbol'] == token2_symbol) or
                (pair['token1']['symbol'] == token2_symbol and pair['token2']['symbol'] == token1_symbol)):
                return pair
        return None
    
    async def refresh_pair_data(self, pair: Dict) -> Dict:
        """Refresh data for a specific pair"""
        try:
            updated_pair = await self.check_single_pair(
                pair['token1']['symbol'],
                pair['token2']['symbol']
            )
            if updated_pair:
                # Preserve rank and score
                updated_pair['rank'] = pair.get('rank', 999)
                updated_pair['score'] = pair.get('score', 0)
                return updated_pair
            else:
                return pair  # Return original if refresh failed
        except Exception as e:
            logger.error(f"Error refreshing pair data: {e}")
            return pair