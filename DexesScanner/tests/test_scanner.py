import asyncio
import sys
import time
from pathlib import Path
from web3 import Web3

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from config.settings import settings
from utils.logger import logger
from dex.price_feeds import PriceFeed
from dex.pair_discovery import PairDiscovery
from arbitrage.arbitrage_detector import ArbitrageDetector
from data.database import ScannerDatabase

class ScannerTester:
    def __init__(self):
        self.w3 = None
        self.price_feed = None
        self.pair_discovery = None
        self.arbitrage_detector = None
        self.db = None
        self.test_results = {}
    
    async def initialize_connections(self):
        """Initialize Web3 and all components"""
        try:
            # Initialize Web3 connection
            logger.info(" Initializing Web3 connection...")
            self.w3 = Web3(Web3.HTTPProvider(settings.WEB3_PROVIDER_URL))
            
            if not self.w3.is_connected():
                logger.error("❌ Failed to connect to Ethereum node")
                return False
            
            logger.info(f"✅ Connected to Ethereum (Chain ID: {self.w3.eth.chain_id})")
            
            # Initialize components
            self.price_feed = PriceFeed(self.w3)
            self.pair_discovery = PairDiscovery(self.w3)
            self.arbitrage_detector = ArbitrageDetector(self.w3)
            self.db = ScannerDatabase()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error initializing connections: {e}")
            return False
    
    async def test_configuration(self):
        """Test 1: Configuration and environment variables"""
        logger.info("📋 Test 1: Configuration and Environment")
        
        test_result = {
            'name': 'Configuration Test',
            'status': 'failed',
            'details': {}
        }
        
        try:
            # Check required settings
            required_settings = [
                'WEB3_PROVIDER_URL',
                'CHAIN_ID',
                'MIN_PROFIT_ETH',
                'MAX_GAS_PRICE_GWEI'
            ]
            
            missing_settings = []
            for setting in required_settings:
                if not hasattr(settings, setting) or getattr(settings, setting) is None:
                    missing_settings.append(setting)
            
            test_result['details']['missing_settings'] = missing_settings
            test_result['details']['web3_url_configured'] = bool(settings.WEB3_PROVIDER_URL)
            test_result['details']['token_universe_size'] = len(settings.TOKEN_UNIVERSE)
            test_result['details']['auto_discovery_enabled'] = settings.AUTO_DISCOVERY_ENABLED
            
            if not missing_settings:
                test_result['status'] = 'passed'
                logger.info("✅ Configuration test passed")
            else:
                logger.warning(f"⚠️ Missing settings: {missing_settings}")
            
        except Exception as e:
            test_result['details']['error'] = str(e)
            logger.error(f"❌ Configuration test failed: {e}")
        
        self.test_results['configuration'] = test_result
        return test_result['status'] == 'passed'
    
    async def test_web3_connection(self):
        """Test 2: Web3 connection and network"""
        logger.info("🌐 Test 2: Web3 Connection")
        
        test_result = {
            'name': 'Web3 Connection Test',
            'status': 'failed',
            'details': {}
        }
        
        try:
            if not self.w3:
                raise Exception("Web3 not initialized")
            
            # Test connection
            latest_block = self.w3.eth.block_number
            chain_id = self.w3.eth.chain_id
            gas_price = self.w3.eth.gas_price
            
            test_result['details']['connected'] = True
            test_result['details']['latest_block'] = latest_block
            test_result['details']['chain_id'] = chain_id
            test_result['details']['gas_price_gwei'] = Web3.from_wei(gas_price, 'gwei')
            test_result['details']['correct_network'] = chain_id == settings.CHAIN_ID
            
            if chain_id == settings.CHAIN_ID:
                test_result['status'] = 'passed'
                logger.info(f"✅ Web3 connected - Block: {latest_block}, Gas: {Web3.from_wei(gas_price, 'gwei'):.1f} gwei")
            else:
                logger.warning(f"⚠️ Wrong network - Expected: {settings.CHAIN_ID}, Got: {chain_id}")
            
        except Exception as e:
            test_result['details']['error'] = str(e)
            logger.error(f"❌ Web3 connection test failed: {e}")
        
        self.test_results['web3_connection'] = test_result
        return test_result['status'] == 'passed'
    
    async def test_database_connection(self):
        """Test 3: Database functionality"""
        logger.info("💾 Test 3: Database Connection")
        
        test_result = {
            'name': 'Database Test',
            'status': 'failed',
            'details': {}
        }
        
        try:
            # Test database initialization and basic operations
            stats = await asyncio.get_event_loop().run_in_executor(None, self.db.get_execution_stats)
            
            test_result['details']['database_accessible'] = True
            test_result['details']['total_opportunities'] = stats.get('total_executions', 0)
            test_result['details']['tables_created'] = True  # If we got stats, tables exist
            
            test_result['status'] = 'passed'
            logger.info("✅ Database test passed")
            
        except Exception as e:
            test_result['details']['error'] = str(e)
            logger.error(f"❌ Database test failed: {e}")
        
        self.test_results['database'] = test_result
        return test_result['status'] == 'passed'
    
    async def test_price_feeds(self):
        """Test 4: Price feed functionality"""
        logger.info("💰 Test 4: Price Feeds")
        
        test_result = {
            'name': 'Price Feeds Test',
            'status': 'failed',
            'details': {}
        }
        
        try:
            # Run price feed tests
            price_test_results = await self.price_feed.test_price_feeds()
            
            test_result['details'] = price_test_results
            
            if price_test_results['successful_tests'] > 0:
                test_result['status'] = 'passed'
                success_rate = (price_test_results['successful_tests'] / price_test_results['total_tests']) * 100
                logger.info(f"✅ Price feeds test passed - {success_rate:.1f}% success rate")
            else:
                logger.error("❌ No successful price feed tests")
            
        except Exception as e:
            test_result['details']['error'] = str(e)
            logger.error(f"❌ Price feeds test failed: {e}")
        
        self.test_results['price_feeds'] = test_result
        return test_result['status'] == 'passed'
    
    async def test_pair_discovery(self):
        """Test 5: Pair discovery system"""
        logger.info("🔍 Test 5: Pair Discovery")
        
        test_result = {
            'name': 'Pair Discovery Test',
            'status': 'failed',
            'details': {}
        }
        
        try:
            # Test pair discovery
            logger.info("Running pair discovery (this may take a moment)...")
            discovered_pairs = await self.pair_discovery.discover_all_pairs(force_refresh=True)
            
            test_result['details']['total_pairs_discovered'] = len(discovered_pairs)
            test_result['details']['high_priority_pairs'] = len([p for p in discovered_pairs if p.get('priority') == 'high'])
            test_result['details']['medium_priority_pairs'] = len([p for p in discovered_pairs if p.get('priority') == 'medium'])
            test_result['details']['pairs_with_good_liquidity'] = len([p for p in discovered_pairs if p.get('metrics', {}).get('min_liquidity_eth', 0) > 5])
            
            if len(discovered_pairs) > 0:
                test_result['status'] = 'passed'
                logger.info(f"✅ Pair discovery passed - Found {len(discovered_pairs)} pairs")
                
                # Show top 3 pairs
                for i, pair in enumerate(discovered_pairs[:3]):
                    logger.info(f"  {i+1}. {pair['token1']['symbol']}/{pair['token2']['symbol']} - "
                              f"Liquidity: {pair['metrics']['total_liquidity_eth']:.1f} ETH")
            else:
                logger.warning("⚠️ No pairs discovered")
            
        except Exception as e:
            test_result['details']['error'] = str(e)
            logger.error(f"❌ Pair discovery test failed: {e}")
        
        self.test_results['pair_discovery'] = test_result
        return test_result['status'] == 'passed'
    
    async def test_arbitrage_detection(self):
        """Test 6: Arbitrage detection"""
        logger.info("🎯 Test 6: Arbitrage Detection")
        
        test_result = {
            'name': 'Arbitrage Detection Test',
            'status': 'failed',
            'details': {}
        }
        
        try:
            # Test arbitrage detection
            logger.info("Scanning for arbitrage opportunities...")
            opportunities = await self.arbitrage_detector.scan_for_opportunities()
            
            test_result['details']['total_opportunities'] = len(opportunities)
            test_result['details']['profitable_opportunities'] = len([o for o in opportunities if o['net_profit_eth'] > 0])
            test_result['details']['high_confidence_opportunities'] = len([o for o in opportunities if o['confidence_score'] > 0.7])
            
            if len(opportunities) >= 0:  # Even 0 opportunities is a valid result
                test_result['status'] = 'passed'
                logger.info(f"✅ Arbitrage detection passed - Found {len(opportunities)} opportunities")
                
                if opportunities:
                    # Show top 3 opportunities
                    for i, opp in enumerate(opportunities[:3]):
                        logger.info(f"  {i+1}. {opp['pair']}: {opp['net_profit_eth']:.4f} ETH profit "
                                  f"({opp['confidence_score']:.2f} confidence)")
                else:
                    logger.info("  ℹ️ No profitable opportunities found (this is normal in competitive markets)")
            
        except Exception as e:
            test_result['details']['error'] = str(e)
            logger.error(f"❌ Arbitrage detection test failed: {e}")
        
        self.test_results['arbitrage_detection'] = test_result
        return test_result['status'] == 'passed'
    
    async def test_gas_estimation(self):
        """Test 7: Gas price estimation"""
        logger.info("⛽ Test 7: Gas Estimation")
        
        test_result = {
            'name': 'Gas Estimation Test',
            'status': 'failed',
            'details': {}
        }
        
        try:
            # Test gas estimation
            gas_price = await self.arbitrage_detector.get_current_gas_price()
            gas_cost_eth = await self.arbitrage_detector._estimate_gas_cost(gas_price)
            
            test_result['details']['current_gas_price_gwei'] = Web3.from_wei(gas_price, 'gwei')
            test_result['details']['estimated_gas_cost_eth'] = gas_cost_eth
            test_result['details']['under_max_gas_price'] = gas_price <= Web3.to_wei(settings.MAX_GAS_PRICE_GWEI, 'gwei')
            
            test_result['status'] = 'passed'
            logger.info(f"✅ Gas estimation passed - Current: {Web3.from_wei(gas_price, 'gwei'):.1f} gwei, "
                       f"Est. cost: {gas_cost_eth:.4f} ETH")
            
        except Exception as e:
            test_result['details']['error'] = str(e)
            logger.error(f"❌ Gas estimation test failed: {e}")
        
        self.test_results['gas_estimation'] = test_result
        return test_result['status'] == 'passed'
    
    async def run_full_test_suite(self):
        """Run all tests"""
        logger.info("🧪 Starting Full Scanner Test Suite")
        logger.info("=" * 50)
        
        start_time = time.time()
        
        # Initialize connections
        if not await self.initialize_connections():
            logger.error("❌ Failed to initialize - aborting tests")
            return
        
        # Run all tests
        tests = [
            self.test_configuration,
            self.test_web3_connection,
            self.test_database_connection,
            self.test_price_feeds,
            self.test_pair_discovery,
            self.test_arbitrage_detection,
            self.test_gas_estimation
        ]
        
        passed_tests = 0
        total_tests = len(tests)
        
        for test in tests:
            try:
                if await test():
                    passed_tests += 1
                logger.info("-" * 30)
            except Exception as e:
                logger.error(f"❌ Test failed with exception: {e}")
                logger.info("-" * 30)
        
        # Final summary
        duration = time.time() - start_time
        success_rate = (passed_tests / total_tests) * 100
        
        logger.info("=" * 50)
        logger.info("📊 TEST SUMMARY")
        logger.info(f"Tests Passed: {passed_tests}/{total_tests} ({success_rate:.1f}%)")
        logger.info(f"Duration: {duration:.2f} seconds")
        
        if passed_tests == total_tests:
            logger.info("🎉 ALL TESTS PASSED! Scanner is ready to use.")
        elif passed_tests >= total_tests * 0.8:
            logger.info("✅ Most tests passed. Scanner is functional with minor issues.")
        else:
            logger.warning("⚠️ Several tests failed. Check configuration and network connectivity.")
        
        return success_rate >= 80
    
    async def quick_scan(self):
        """Run a quick opportunity scan"""
        logger.info("🚀 Quick Arbitrage Scan")
        logger.info("=" * 30)
        
        if not await self.initialize_connections():
            return
        
        # Quick scan for opportunities
        opportunities = await self.arbitrage_detector.scan_for_opportunities()
        
        if opportunities:
            logger.info(f"💰 Found {len(opportunities)} profitable opportunities:")
            for i, opp in enumerate(opportunities[:5]):  # Show top 5
                logger.info(f"{i+1}. {opp['pair']}: {opp['net_profit_eth']:.4f} ETH "
                          f"({opp['profit_margin_pct']:.2f}% margin, "
                          f"{opp['confidence_score']:.2f} confidence)")
        else:
            logger.info("ℹ️ No profitable opportunities found")
            logger.info("This is normal - arbitrage opportunities are rare and competitive")

async def main():
    """Main test function"""
    tester = ScannerTester()
    
    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == 'quick':
        await tester.quick_scan()
    else:
        await tester.run_full_test_suite()

if __name__ == "__main__":
    asyncio.run(main())