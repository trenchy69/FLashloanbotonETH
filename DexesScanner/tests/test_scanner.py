# tests/test_scanner.py
import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from config.settings import settings
from dex.price_feeds import price_manager
from arbitrage.arbitrage_detector import arbitrage_detector
from data.database import db
from utils.logger import log_info, log_error, logger

class ScannerTester:
    """Test suite for the arbitrage scanner"""
    
    def __init__(self):
        self.test_results = []
    
    async def test_configuration(self):
        """Test if configuration is valid"""
        log_info("🔧 Testing Configuration...")
        
        try:
            # Check required settings
            missing = settings.validate()
            if missing:
                log_error(f"❌ Missing required settings: {', '.join(missing)}")
                return False
            
            # Check enabled paths
            enabled_paths = settings.dynamic.get_enabled_paths()
            log_info(f"✅ Configuration valid - {len(enabled_paths)} paths enabled")
            
            for path in enabled_paths:
                log_info(f"   Path {path['id']}: {path['name']}")
            
            return True
            
        except Exception as e:
            log_error("❌ Configuration test failed", e)
            return False
    
    async def test_price_feeds(self):
        """Test price feed connectivity"""
        log_info("💰 Testing Price Feeds...")
        
        try:
            success = await price_manager.test_price_feeds()
            
            if success:
                log_info("✅ Price feeds working correctly")
                return True
            else:
                log_error("❌ Price feeds failed")
                return False
                
        except Exception as e:
            log_error("❌ Price feed test failed", e)
            return False
    
    async def test_database(self):
        """Test database functionality"""
        log_info("💾 Testing Database...")
        
        try:
            # Test database connection
            stats = db.get_execution_stats(7)
            log_info(f"✅ Database connected - {stats.get('total_executions', 0)} historical executions")
            return True
            
        except Exception as e:
            log_error("❌ Database test failed", e)
            return False
    
    async def test_opportunity_detection(self):
        """Test arbitrage opportunity detection"""
        log_info("🔍 Testing Opportunity Detection...")
        
        try:
            # Run one scan for opportunities
            opportunities = await arbitrage_detector.scan_for_opportunities()
            
            log_info(f"📊 Scan Results:")
            log_info(f"   Found {len(opportunities)} opportunities")
            
            if opportunities:
                log_info("✅ Top opportunities found:")
                
                for i, opp in enumerate(opportunities[:3]):  # Show top 3
                    log_info(f"   #{i+1} Path {opp.path_id} ({opp.path_name}):")
                    log_info(f"      Trade: {opp.trade_amount_eth:.2f} ETH")
                    log_info(f"      Gross Profit: {opp.expected_profit_eth:.6f} ETH (${opp.expected_profit_usd:.2f})")
                    log_info(f"      Gas Cost: {opp.gas_cost_eth:.6f} ETH (${opp.gas_cost_usd:.2f})")
                    log_info(f"      Net Profit: {opp.net_profit_eth:.6f} ETH (${opp.net_profit_usd:.2f})")
                    log_info(f"      ROI: {opp.profit_percentage:.3f}%")
                    log_info(f"      Confidence: {opp.confidence_score:.2f}/1.0")
                    log_info("")
                
                return True
            else:
                log_info("⚠️ No profitable opportunities found")
                log_info("   This could be normal - arbitrage opportunities are rare and competitive")
                return True  # Not finding opportunities is not a failure
                
        except Exception as e:
            log_error("❌ Opportunity detection test failed", e)
            return False
    
    async def test_price_data_quality(self):
        """Test quality of price data"""
        log_info("📈 Testing Price Data Quality...")
        
        try:
            # Get prices for all paths
            all_prices = await price_manager.get_all_path_prices()
            
            if not all_prices:
                log_error("❌ No price data available")
                return False
            
            log_info(f"✅ Price data available for {len(all_prices)} paths")
            
            # Check each path's price data
            for path_id, prices in all_prices.items():
                path_info = settings.paths.get_path_by_id(path_id)
                log_info(f"   Path {path_id} ({path_info['name']}):")
                
                for dex, price_data in prices.items():
                    log_info(f"      {dex.capitalize()}: Price={price_data.price:.6f}, Liquidity={price_data.liquidity_eth:.2f} ETH")
                
                # Calculate price difference
                if 'uniswap' in prices and 'sushiswap' in prices:
                    uni_price = prices['uniswap'].price
                    sushi_price = prices['sushiswap'].price
                    
                    # For comparison, we need to consider the direction
                    if uni_price > 0 and sushi_price > 0:
                        price_diff = abs(uni_price - (1/sushi_price)) / uni_price * 100
                        log_info(f"      Price Difference: {price_diff:.3f}%")
                
                log_info("")
            
            return True
            
        except Exception as e:
            log_error("❌ Price data quality test failed", e)
            return False
    
    async def test_gas_estimation(self):
        """Test gas cost estimation"""
        log_info("⛽ Testing Gas Estimation...")
        
        try:
            gas_estimator = arbitrage_detector.calculator.gas_estimator
            
            # Update gas price
            current_gas = await gas_estimator.get_current_gas_price()
            log_info(f"   Current gas price: {current_gas} gwei")
            
            # Test gas estimation for different trade sizes
            test_amounts = [0.1, 1.0, 5.0]
            
            for amount in test_amounts:
                gas_eth, gas_usd = gas_estimator.estimate_gas_cost(amount)
                log_info(f"   {amount} ETH trade: {gas_eth:.6f} ETH (${gas_usd:.2f}) gas cost")
            
            log_info("✅ Gas estimation working")
            return True
            
        except Exception as e:
            log_error("❌ Gas estimation test failed", e)
            return False
    
    async def run_full_test_suite(self):
        """Run all tests"""
        logger.startup_log()
        log_info("🚀 Starting Scanner Test Suite")
        log_info("=" * 60)
        
        tests = [
            ("Configuration", self.test_configuration()),
            ("Database", self.test_database()),
            ("Price Feeds", self.test_price_feeds()),
            ("Price Data Quality", self.test_price_data_quality()),
            ("Gas Estimation", self.test_gas_estimation()),
            ("Opportunity Detection", self.test_opportunity_detection()),
        ]
        
        passed = 0
        total = len(tests)
        
        for test_name, test_coro in tests:
            log_info(f"\n📋 Running {test_name} Test...")
            try:
                result = await test_coro
                if result:
                    passed += 1
                    log_info(f"✅ {test_name} Test: PASSED")
                else:
                    log_error(f"❌ {test_name} Test: FAILED")
            except Exception as e:
                log_error(f"❌ {test_name} Test: FAILED with exception", e)
        
        log_info("\n" + "=" * 60)
        log_info(f"🏁 Test Suite Complete: {passed}/{total} tests passed")
        
        if passed == total:
            log_info("🎉 All tests passed! Scanner is ready to use.")
        else:
            log_error(f"⚠️ {total - passed} tests failed. Please fix issues before proceeding.")
        
        return passed == total

async def quick_scan():
    """Quick scan to see current opportunities"""
    log_info("🔍 Running Quick Opportunity Scan...")
    
    opportunities = await arbitrage_detector.scan_for_opportunities()
    
    if opportunities:
        log_info(f"📊 Found {len(opportunities)} opportunities:")
        
        for opp in opportunities:
            profit_eth = opp.net_profit_eth
            profit_usd = opp.net_profit_usd
            roi = opp.profit_percentage
            
            log_info(f"💰 Path {opp.path_id}: {profit_eth:.6f} ETH (${profit_usd:.2f}) profit, ROI: {roi:.3f}%")
    else:
        log_info("📭 No profitable opportunities found at this time")

async def main():
    """Main test runner"""
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        # Quick scan mode
        await quick_scan()
    else:
        # Full test suite
        tester = ScannerTester()
        success = await tester.run_full_test_suite()
        
        if not success:
            sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_info("Test interrupted by user")
    except Exception as e:
        log_error("Test suite failed", e)
        sys.exit(1)