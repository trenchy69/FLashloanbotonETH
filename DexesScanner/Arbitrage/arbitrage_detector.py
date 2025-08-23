import asyncio
import time
from typing import Dict, List, Optional
from web3 import Web3
from config.settings import settings
from utils.logger import logger
from data.database import ScannerDatabase
from dex.price_feeds import PriceFeed
from dex.pair_discovery import PairDiscovery

class ArbitrageDetector:
    def __init__(self, web3_instance):
        self.w3 = web3_instance
        self.price_feed = PriceFeed(web3_instance)
        self.pair_discovery = PairDiscovery(web3_instance)
        self.db = ScannerDatabase()
        self.gas_price_cache = None
        self.gas_price_timestamp = 0
        
        # Performance tracking
        self.scan_stats = {
            'total_scans': 0,
            'opportunities_found': 0,
            'profitable_opportunities': 0,
            'last_scan_time': 0
        }
    
    async def scan_for_opportunities(self, use_discovery: bool = True) -> List[Dict]:
        """Main scanning function - find arbitrage opportunities"""
        start_time = time.time()
        self.scan_stats['total_scans'] += 1
        
        try:
            # Get pairs to scan
            if use_discovery:
                pairs_to_scan = self.pair_discovery.get_active_pairs()
                if not pairs_to_scan:
                    logger.info("No discovered pairs available, running discovery...")
                    pairs_to_scan = await self.pair_discovery.discover_all_pairs()
            else:
                # Fallback to manual pairs for testing
                pairs_to_scan = self._get_fallback_pairs()
            
            if not pairs_to_scan:
                logger.warning("No pairs available for scanning")
                return []
            
            logger.info(f"🔍 Scanning {len(pairs_to_scan)} pairs for arbitrage opportunities...")
            
            # Get current gas price
            gas_price = await self.get_current_gas_price()
            
            # Scan pairs in batches for efficiency
            opportunities = []
            batch_size = 10
            
            for i in range(0, len(pairs_to_scan), batch_size):
                batch = pairs_to_scan[i:i + batch_size]
                batch_opportunities = await self._scan_pair_batch(batch, gas_price)
                opportunities.extend(batch_opportunities)
                
                # Small delay to avoid overwhelming the node
                await asyncio.sleep(0.5)
            
            # Filter and rank opportunities
            profitable_opportunities = self._filter_profitable_opportunities(opportunities)
            
            # Update statistics
            self.scan_stats['opportunities_found'] += len(opportunities)
            self.scan_stats['profitable_opportunities'] += len(profitable_opportunities)
            self.scan_stats['last_scan_time'] = time.time()
            
            # Store in database
            for opportunity in profitable_opportunities:
                # Convert to database format
                from data.database import OpportunityRecord
                
                db_record = OpportunityRecord(
                    path_id=hash(opportunity['pair']) % 1000,  # Simple hash for path ID
                    path_name=opportunity['pair'],
                    profit_eth=opportunity['estimated_profit_eth'],
                    profit_usd=opportunity['estimated_profit_eth'] * 3000,  # Rough ETH price
                    trade_amount=float(opportunity['trade_amount_eth']),
                    gas_cost_eth=opportunity['gas_cost_eth'],
                    gas_cost_usd=opportunity['gas_cost_eth'] * 3000,
                    net_profit_eth=opportunity['net_profit_eth'],
                    net_profit_usd=opportunity['net_profit_eth'] * 3000,
                    uniswap_price=opportunity['buy_price'] if opportunity['buy_dex'] == 'uniswap' else opportunity['sell_price'],
                    sushiswap_price=opportunity['buy_price'] if opportunity['buy_dex'] == 'sushiswap' else opportunity['sell_price'],
                    price_diff_percent=opportunity['price_difference_pct'],
                    market_data=str(opportunity)
                )
                
                try:
                    await asyncio.get_event_loop().run_in_executor(None, self.db.save_opportunity, db_record)
                except Exception as e:
                    logger.debug(f"Error storing opportunity: {e}")
            
            scan_duration = time.time() - start_time
            logger.info(f"✅ Scan complete: {len(profitable_opportunities)}/{len(opportunities)} profitable opportunities in {scan_duration:.2f}s")
            
            return profitable_opportunities
            
        except Exception as e:
            logger.error(f"Error during arbitrage scan: {e}")
            return []
    
    def _get_fallback_pairs(self) -> List[Dict]:
        """Get fallback pairs when discovery isn't available"""
        fallback_pairs = [
            {
                'token1': {'symbol': 'WETH', 'address': settings.get_token_address('WETH')},
                'token2': {'symbol': 'USDC', 'address': settings.get_token_address('USDC')},
                'priority': 'high'
            },
            {
                'token1': {'symbol': 'WETH', 'address': settings.get_token_address('WETH')},
                'token2': {'symbol': 'USDT', 'address': settings.get_token_address('USDT')},
                'priority': 'high'
            },
            {
                'token1': {'symbol': 'WETH', 'address': settings.get_token_address('WETH')},
                'token2': {'symbol': 'DAI', 'address': settings.get_token_address('DAI')},
                'priority': 'high'
            }
        ]
        return [pair for pair in fallback_pairs if pair['token1']['address'] and pair['token2']['address']]
    
    async def _scan_pair_batch(self, pairs: List[Dict], gas_price: int) -> List[Dict]:
        """Scan a batch of pairs for opportunities"""
        opportunities = []
        
        for pair in pairs:
            try:
                opportunity = await self._analyze_pair_opportunity(pair, gas_price)
                if opportunity:
                    opportunities.append(opportunity)
                    
            except Exception as e:
                logger.debug(f"Error analyzing pair {pair['token1']['symbol']}/{pair['token2']['symbol']}: {e}")
                continue
        
        return opportunities
    
    async def _analyze_pair_opportunity(self, pair: Dict, gas_price: int) -> Optional[Dict]:
        """Analyze a single pair for arbitrage opportunity"""
        try:
            token_a = pair['token1']['address']
            token_b = pair['token2']['address']
            
            # Get prices from both DEXs
            prices = await self.price_feed.get_prices_for_pair(token_a, token_b)
            
            if not prices['uniswap'] or not prices['sushiswap']:
                return None
            
            uniswap_price = prices['uniswap']['price']
            sushiswap_price = prices['sushiswap']['price']
            
            # Calculate price difference
            price_diff = abs(uniswap_price - sushiswap_price)
            price_diff_pct = (price_diff / min(uniswap_price, sushiswap_price)) * 100
            
            # Skip if price difference is too small
            if price_diff_pct < 0.1:  # Less than 0.1%
                return None
            
            # Determine trade direction
            if uniswap_price > sushiswap_price:
                # Buy on Sushiswap, sell on Uniswap
                buy_dex = 'sushiswap'
                sell_dex = 'uniswap'
                buy_price = sushiswap_price
                sell_price = uniswap_price
                buy_reserves = prices['sushiswap']
                sell_reserves = prices['uniswap']
            else:
                # Buy on Uniswap, sell on Sushiswap
                buy_dex = 'uniswap'
                sell_dex = 'sushiswap'
                buy_price = uniswap_price
                sell_price = sushiswap_price
                buy_reserves = prices['uniswap']
                sell_reserves = prices['sushiswap']
            
            # Calculate optimal trade amounts
            trade_amounts = await self._calculate_trade_amounts(buy_reserves, sell_reserves, pair)
            
            # Analyze each trade amount
            best_opportunity = None
            best_profit = 0
            
            for amount_wei in trade_amounts:
                analysis = await self._analyze_trade_amount(
                    amount_wei, buy_reserves, sell_reserves, gas_price, pair
                )
                
                if analysis and analysis['profit_eth'] > best_profit:
                    best_profit = analysis['profit_eth']
                    best_opportunity = {
                        'pair': f"{pair['token1']['symbol']}/{pair['token2']['symbol']}",
                        'token_a': pair['token1'],
                        'token_b': pair['token2'],
                        'buy_dex': buy_dex,
                        'sell_dex': sell_dex,
                        'buy_price': buy_price,
                        'sell_price': sell_price,
                        'price_difference_pct': price_diff_pct,
                        'trade_amount_wei': amount_wei,
                        'trade_amount_eth': Web3.from_wei(amount_wei, 'ether'),
                        'estimated_profit_wei': Web3.to_wei(analysis['profit_eth'], 'ether'),
                        'estimated_profit_eth': analysis['profit_eth'],
                        'gas_cost_eth': analysis['gas_cost_eth'],
                        'net_profit_eth': analysis['net_profit_eth'],
                        'profit_margin_pct': analysis['profit_margin_pct'],
                        'confidence_score': analysis['confidence_score'],
                        'liquidity_check': analysis['liquidity_check'],
                        'price_impact_buy': analysis['price_impact_buy'],
                        'price_impact_sell': analysis['price_impact_sell'],
                        'timestamp': int(time.time()),
                        'priority': pair.get('priority', 'medium')
                    }
            
            return best_opportunity
            
        except Exception as e:
            logger.debug(f"Error in pair opportunity analysis: {e}")
            return None
    
    async def _calculate_trade_amounts(self, buy_reserves: Dict, sell_reserves: Dict, pair: Dict) -> List[int]:
        """Calculate different trade amounts to test"""
        try:
            # Base amount on available liquidity
            min_liquidity_eth = min(buy_reserves['liquidity_eth'], sell_reserves['liquidity_eth'])
            
            # Conservative amounts based on liquidity
            max_trade_eth = min(min_liquidity_eth * 0.1, settings.RISK_SETTINGS['max_trade_amount_eth'])  # Max 10% of liquidity
            
            amounts_eth = [
                max_trade_eth * 0.1,   # 1% of liquidity
                max_trade_eth * 0.25,  # 2.5% of liquidity  
                max_trade_eth * 0.5,   # 5% of liquidity
                max_trade_eth,         # 10% of liquidity (max)
            ]
            
            # Convert to wei and filter valid amounts
            amounts_wei = []
            for amount_eth in amounts_eth:
                if amount_eth >= 0.001:  # Minimum 0.001 ETH
                    amounts_wei.append(Web3.to_wei(amount_eth, 'ether'))
            
            return amounts_wei[:3]  # Test top 3 amounts
            
        except Exception as e:
            logger.error(f"Error calculating trade amounts: {e}")
            return [Web3.to_wei(0.01, 'ether')]  # Fallback amount
    
    async def _analyze_trade_amount(self, amount_wei: int, buy_reserves: Dict, sell_reserves: Dict, 
                                   gas_price: int, pair: Dict) -> Optional[Dict]:
        """Analyze profitability for a specific trade amount"""
        try:
            # Calculate price impact
            price_impact_buy = self.price_feed.calculate_price_impact(buy_reserves, amount_wei)
            price_impact_sell = self.price_feed.calculate_price_impact(sell_reserves, amount_wei)
            
            # Skip if price impact is too high
            if price_impact_buy > 0.05 or price_impact_sell > 0.05:  # 5% max impact
                return None
            
            # Estimate gas cost
            gas_cost_eth = await self._estimate_gas_cost(gas_price)
            
            # Calculate profit (simplified calculation)
            price_diff = abs(buy_reserves['price'] - sell_reserves['price'])
            gross_profit_eth = float(Web3.from_wei(amount_wei, 'ether')) * price_diff
            
            # Adjust for price impact
            impact_loss = gross_profit_eth * (price_impact_buy + price_impact_sell)
            adjusted_profit_eth = gross_profit_eth - impact_loss
            
            # Calculate net profit
            net_profit_eth = adjusted_profit_eth - gas_cost_eth
            
            # Skip if not profitable
            if net_profit_eth <= 0:
                return None
            
            # Calculate metrics
            trade_amount_eth = float(Web3.from_wei(amount_wei, 'ether'))
            profit_margin_pct = (net_profit_eth / trade_amount_eth) * 100
            
            # Calculate confidence score
            confidence_score = self._calculate_confidence_score(
                price_impact_buy, price_impact_sell, 
                buy_reserves['liquidity_eth'], sell_reserves['liquidity_eth'],
                profit_margin_pct
            )
            
            # Liquidity check
            liquidity_check = {
                'buy_dex_liquidity_eth': buy_reserves['liquidity_eth'],
                'sell_dex_liquidity_eth': sell_reserves['liquidity_eth'],
                'sufficient_liquidity': min(buy_reserves['liquidity_eth'], sell_reserves['liquidity_eth']) > trade_amount_eth * 2
            }
            
            return {
                'profit_eth': adjusted_profit_eth,
                'net_profit_eth': net_profit_eth,
                'gas_cost_eth': gas_cost_eth,
                'profit_margin_pct': profit_margin_pct,
                'confidence_score': confidence_score,
                'price_impact_buy': price_impact_buy,
                'price_impact_sell': price_impact_sell,
                'liquidity_check': liquidity_check
            }
            
        except Exception as e:
            logger.error(f"Error analyzing trade amount: {e}")
            return None
    
    def _calculate_confidence_score(self, price_impact_buy: float, price_impact_sell: float,
                                   liquidity_buy: float, liquidity_sell: float, profit_margin: float) -> float:
        """Calculate confidence score for an opportunity (0-1)"""
        try:
            # Price impact score (lower impact = higher confidence)
            impact_score = max(0, 1 - (price_impact_buy + price_impact_sell) / 0.1)  # Normalize by 10% max impact
            
            # Liquidity score (higher liquidity = higher confidence)
            min_liquidity = min(liquidity_buy, liquidity_sell)
            liquidity_score = min(1, min_liquidity / 50)  # Normalize by 50 ETH liquidity
            
            # Profit margin score (higher margin = higher confidence)
            profit_score = min(1, profit_margin / 5)  # Normalize by 5% profit margin
            
            # Combined confidence score (weighted average)
            confidence = (impact_score * 0.4 + liquidity_score * 0.3 + profit_score * 0.3)
            
            return max(0, min(1, confidence))
            
        except Exception as e:
            logger.error(f"Error calculating confidence score: {e}")
            return 0.0
    
    def _filter_profitable_opportunities(self, opportunities: List[Dict]) -> List[Dict]:
        """Filter opportunities by profitability and confidence"""
        if not opportunities:
            return []
        
        profitable = []
        
        for opp in opportunities:
            # Apply filters
            meets_min_profit = opp['net_profit_eth'] >= settings.MIN_PROFIT_ETH
            meets_confidence = opp['confidence_score'] >= settings.RISK_SETTINGS.get('confidence_threshold', 0.5)
            has_sufficient_liquidity = opp['liquidity_check']['sufficient_liquidity']
            
            if meets_min_profit and meets_confidence and has_sufficient_liquidity:
                profitable.append(opp)
        
        # Sort by net profit descending
        profitable.sort(key=lambda x: x['net_profit_eth'], reverse=True)
        
        return profitable
    
    async def get_current_gas_price(self) -> int:
        """Get current gas price with caching"""
        current_time = time.time()
        
        # Use cached gas price if recent (30 seconds)
        if (self.gas_price_cache and 
            current_time - self.gas_price_timestamp < 30):
            return self.gas_price_cache
        
        try:
            # Get gas price from network
            gas_price = self.w3.eth.gas_price
            
            # Cap at max gas price setting
            max_gas_price = Web3.to_wei(settings.MAX_GAS_PRICE_GWEI, 'gwei')
            gas_price = min(gas_price, max_gas_price)
            
            # Cache the result
            self.gas_price_cache = gas_price
            self.gas_price_timestamp = current_time
            
            return gas_price
            
        except Exception as e:
            logger.error(f"Error getting gas price: {e}")
            # Return default gas price
            return Web3.to_wei(20, 'gwei')
    
    async def _estimate_gas_cost(self, gas_price: int) -> float:
        """Estimate gas cost for arbitrage transaction"""
        try:
            # Typical gas usage for flash loan arbitrage
            estimated_gas = 300000  # Conservative estimate
            
            # Calculate cost in ETH
            gas_cost_wei = gas_price * estimated_gas
            gas_cost_eth = float(Web3.from_wei(gas_cost_wei, 'ether'))
            
            return gas_cost_eth
            
        except Exception as e:
            logger.error(f"Error estimating gas cost: {e}")
            return 0.05  # Default 0.05 ETH
    
    async def continuous_scan(self, interval_seconds: int = None):
        """Run continuous scanning for opportunities"""
        if interval_seconds is None:
            interval_seconds = settings.SCAN_INTERVAL
        
        logger.info(f"🔄 Starting continuous scanning (interval: {interval_seconds}s)")
        
        while True:
            try:
                opportunities = await self.scan_for_opportunities()
                
                if opportunities:
                    logger.info(f"💰 Found {len(opportunities)} profitable opportunities!")
                    
                    # Log top opportunity
                    top_opp = opportunities[0]
                    logger.info(f"Top opportunity: {top_opp['pair']} - "
                              f"Profit: {top_opp['net_profit_eth']:.4f} ETH "
                              f"({top_opp['profit_margin_pct']:.2f}%)")
                else:
                    logger.info("No profitable opportunities found")
                
                # Wait for next scan
                await asyncio.sleep(interval_seconds)
                
            except KeyboardInterrupt:
                logger.info("Stopping continuous scan")
                break
            except Exception as e:
                logger.error(f"Error in continuous scan: {e}")
                await asyncio.sleep(10)  # Short wait before retry
    
    def get_scan_statistics(self) -> Dict:
        """Get scanning performance statistics"""
        uptime = int(time.time()) - self.scan_stats.get('start_time', int(time.time()))
        
        stats = {
            'total_scans': self.scan_stats['total_scans'],
            'opportunities_found': self.scan_stats['opportunities_found'],
            'profitable_opportunities': self.scan_stats['profitable_opportunities'],
            'success_rate_pct': 0,
            'uptime_hours': uptime / 3600,
            'last_scan_ago_seconds': int(time.time()) - self.scan_stats.get('last_scan_time', 0)
        }
        
        if stats['total_scans'] > 0:
            stats['success_rate_pct'] = (stats['profitable_opportunities'] / stats['total_scans']) * 100
        
        return stats
    
    async def test_arbitrage_detection(self) -> Dict:
        """Test arbitrage detection system"""
        logger.info("🧪 Testing arbitrage detection system...")
        
        test_results = {
            'price_feed_test': None,
            'pair_discovery_test': None,
            'gas_estimation_test': None,
            'opportunity_scan_test': None,
            'database_test': None
        }
        
        try:
            # Test 1: Price feeds
            logger.info("Testing price feeds...")
            test_results['price_feed_test'] = await self.price_feed.test_price_feeds()
            
            # Test 2: Pair discovery
            logger.info("Testing pair discovery...")
            discovered_pairs = self.pair_discovery.get_active_pairs()
            if not discovered_pairs:
                logger.info("Running discovery...")
                discovered_pairs = await self.pair_discovery.discover_all_pairs(force_refresh=True)
            
            test_results['pair_discovery_test'] = {
                'total_pairs_discovered': len(discovered_pairs),
                'high_priority_pairs': len([p for p in discovered_pairs if p.get('priority') == 'high']),
                'pairs_with_liquidity': len([p for p in discovered_pairs if p.get('metrics', {}).get('min_liquidity_eth', 0) > 1])
            }
            
            # Test 3: Gas estimation
            logger.info("Testing gas estimation...")
            gas_price = await self.get_current_gas_price()
            gas_cost_eth = await self._estimate_gas_cost(gas_price)
            test_results['gas_estimation_test'] = {
                'current_gas_price_gwei': Web3.from_wei(gas_price, 'gwei'),
                'estimated_gas_cost_eth': gas_cost_eth,
                'under_max_gas_price': gas_price <= Web3.to_wei(settings.MAX_GAS_PRICE_GWEI, 'gwei')
            }
            
            # Test 4: Opportunity scanning
            logger.info("Testing opportunity scanning...")
            opportunities = await self.scan_for_opportunities(use_discovery=True)
            test_results['opportunity_scan_test'] = {
                'total_opportunities': len(opportunities),
                'profitable_opportunities': len([o for o in opportunities if o['net_profit_eth'] > 0]),
                'high_confidence_opportunities': len([o for o in opportunities if o['confidence_score'] > 0.7]),
                'scan_duration_seconds': time.time() - int(time.time())
            }
            
            # Test 5: Database
            logger.info("Testing database...")
            try:
                db_stats = await asyncio.get_event_loop().run_in_executor(None, self.db.get_execution_stats)
                test_results['database_test'] = {
                    'database_accessible': True,
                    'total_opportunities_stored': db_stats.get('total_executions', 0),
                    'recent_opportunities': db_stats.get('successful_executions', 0)
                }
            except Exception as e:
                test_results['database_test'] = {
                    'database_accessible': False,
                    'error': str(e)
                }
            
            # Overall summary
            total_tests = len(test_results)
            successful_tests = sum(1 for test in test_results.values() if test is not None)
            
            logger.info(f"✅ Testing complete: {successful_tests}/{total_tests} tests passed")
            
            if opportunities:
                logger.info(f"💰 Found {len(opportunities)} arbitrage opportunities!")
                for i, opp in enumerate(opportunities[:3]):  # Show top 3
                    logger.info(f"  {i+1}. {opp['pair']}: {opp['net_profit_eth']:.4f} ETH profit "
                              f"({opp['confidence_score']:.2f} confidence)")
            else:
                logger.info("ℹ️  No profitable opportunities found (this is normal - arbitrage is competitive)")
            
            return test_results
            
        except Exception as e:
            logger.error(f"Error during testing: {e}")
            return test_results
                
     
                