# arbitrage/arbitrage_detector.py
import asyncio
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal, getcontext
import time

from config.settings import settings
from dex.price_feeds import price_manager, PriceData
from data.database import db, OpportunityRecord
from utils.logger import log_info, log_error, log_debug, log_opportunity

# Set high precision for financial calculations
getcontext().prec = 28

@dataclass
class ArbitrageOpportunity:
    """Complete arbitrage opportunity data"""
    path_id: int
    path_name: str
    trade_amount_eth: float
    expected_profit_eth: float
    expected_profit_usd: float
    gas_cost_eth: float
    gas_cost_usd: float
    net_profit_eth: float
    net_profit_usd: float
    profit_percentage: float
    price_impact_percent: float
    execution_time_estimate: float
    uniswap_price: float
    sushiswap_price: float
    price_difference_percent: float
    liquidity_eth: float
    confidence_score: float
    timestamp: float

class GasEstimator:
    """Estimates gas costs for arbitrage transactions"""
    
    def __init__(self):
        self.base_gas_limit = 350000  # Base gas for flash swap arbitrage
        self.gas_price_gwei = 20      # Default gas price
        self.eth_price_usd = 2000     # Default ETH price (updated from external source)
    
    async def get_current_gas_price(self) -> int:
        """Get current gas price from network or API"""
        try:
            # For now, use configured max gas price or default
            max_gas = settings.dynamic.get('scanner.max_gas_price', 50)
            current_gas = min(25, max_gas)  # Conservative estimate
            self.gas_price_gwei = current_gas
            return current_gas
            
        except Exception as e:
            log_error("Failed to get current gas price", e)
            return self.gas_price_gwei
    
    def estimate_gas_cost(self, trade_amount_eth: float) -> Tuple[float, float]:
        """Estimate gas cost in ETH and USD"""
        # Larger trades may need more gas due to price impact
        gas_multiplier = 1.0 + (trade_amount_eth / 10.0) * 0.1  # 1% increase per 10 ETH
        estimated_gas = int(self.base_gas_limit * gas_multiplier)
        
        # Gas cost in ETH
        gas_cost_eth = (estimated_gas * self.gas_price_gwei) / 1e9  # Convert gwei to ETH
        
        # Gas cost in USD
        gas_cost_usd = gas_cost_eth * self.eth_price_usd
        
        return gas_cost_eth, gas_cost_usd
    
    def update_eth_price(self, price_usd: float):
        """Update ETH price for gas cost calculations"""
        self.eth_price_usd = price_usd

class ArbitrageCalculator:
    """Calculate arbitrage opportunities from price data"""
    
    def __init__(self):
        self.gas_estimator = GasEstimator()
        self.min_liquidity_eth = 10.0  # Minimum liquidity required
        self.max_price_impact = 5.0    # Maximum acceptable price impact %
    
    def calculate_price_impact(self, trade_amount_eth: float, liquidity_eth: float) -> float:
        """Estimate price impact for a given trade size"""
        if liquidity_eth <= 0:
            return 100.0  # No liquidity = 100% impact
        
        # Simplified price impact calculation
        # Real impact depends on AMM curve (x*y=k)
        impact_percent = (trade_amount_eth / liquidity_eth) * 100
        
        # Apply curve adjustment (impact increases non-linearly)
        if impact_percent > 1:
            impact_percent = impact_percent * (1 + impact_percent / 10)
        
        return min(impact_percent, 100.0)
    
    def calculate_output_with_impact(self, input_amount: float, price: float, 
                                   price_impact_percent: float) -> float:
        """Calculate actual output considering price impact"""
        # Reduce output due to price impact
        impact_factor = 1 - (price_impact_percent / 100)
        effective_price = price * impact_factor
        return input_amount * effective_price
    
    def calculate_arbitrage_profit(self, path_info: Dict, prices: Dict[str, PriceData], 
                                 trade_amount_eth: float) -> Optional[ArbitrageOpportunity]:
        """Calculate arbitrage profit for a specific path and trade amount"""
        try:
            if 'uniswap' not in prices or 'sushiswap' not in prices:
                log_debug(f"Missing price data for path {path_info['id']}")
                return None
            
            uniswap_data = prices['uniswap']
            sushiswap_data = prices['sushiswap']
            
            # Path logic: Buy token on Uniswap, sell on Sushiswap
            # Trade flow: WETH -> Token (Uniswap) -> WETH (Sushiswap)
            
            # Step 1: Calculate how much token we get from Uniswap
            uniswap_liquidity = uniswap_data.liquidity_eth
            uniswap_price_impact = self.calculate_price_impact(trade_amount_eth, uniswap_liquidity)
            
            if uniswap_price_impact > self.max_price_impact:
                log_debug(f"Path {path_info['id']}: Uniswap price impact too high: {uniswap_price_impact:.2f}%")
                return None
            
            # Amount of token received from Uniswap (WETH -> Token)
            token_amount = self.calculate_output_with_impact(
                trade_amount_eth, 
                uniswap_data.price,
                uniswap_price_impact
            )
            
            # Step 2: Calculate how much WETH we get back from Sushiswap
            sushiswap_liquidity = sushiswap_data.liquidity_eth
            
            # For selling token back to WETH, we need to consider the reverse price
            # If sushiswap_data has Token->WETH price, use it directly
            # Otherwise calculate reverse price
            sushiswap_reverse_price = sushiswap_data.price
            
            sushiswap_price_impact = self.calculate_price_impact(
                token_amount * sushiswap_reverse_price,  # Estimate ETH value
                sushiswap_liquidity
            )
            
            if sushiswap_price_impact > self.max_price_impact:
                log_debug(f"Path {path_info['id']}: Sushiswap price impact too high: {sushiswap_price_impact:.2f}%")
                return None
            
            # Amount of WETH received from Sushiswap (Token -> WETH)
            weth_received = self.calculate_output_with_impact(
                token_amount,
                sushiswap_reverse_price,
                sushiswap_price_impact
            )
            
            # Step 3: Calculate profit
            gross_profit_eth = weth_received - trade_amount_eth
            
            # Check minimum profit threshold
            min_profit = settings.dynamic.get('scanner.min_profit_eth', 0.01)
            if gross_profit_eth < min_profit:
                return None
            
            # Step 4: Calculate gas costs
            gas_cost_eth, gas_cost_usd = self.gas_estimator.estimate_gas_cost(trade_amount_eth)
            
            # Step 5: Calculate net profit
            net_profit_eth = gross_profit_eth - gas_cost_eth
            net_profit_usd = net_profit_eth * self.gas_estimator.eth_price_usd
            
            # Only return profitable opportunities
            if net_profit_eth <= 0:
                return None
            
            # Step 6: Calculate additional metrics
            profit_percentage = (net_profit_eth / trade_amount_eth) * 100
            price_diff_percent = abs(uniswap_data.price - (1/sushiswap_reverse_price)) / uniswap_data.price * 100
            
            # Confidence score based on liquidity and price impact
            liquidity_score = min(min(uniswap_liquidity, sushiswap_liquidity) / 100, 1.0)
            impact_score = max(0, 1 - (max(uniswap_price_impact, sushiswap_price_impact) / 10))
            confidence_score = (liquidity_score + impact_score) / 2
            
            opportunity = ArbitrageOpportunity(
                path_id=path_info['id'],
                path_name=path_info['name'],
                trade_amount_eth=trade_amount_eth,
                expected_profit_eth=gross_profit_eth,
                expected_profit_usd=gross_profit_eth * self.gas_estimator.eth_price_usd,
                gas_cost_eth=gas_cost_eth,
                gas_cost_usd=gas_cost_usd,
                net_profit_eth=net_profit_eth,
                net_profit_usd=net_profit_usd,
                profit_percentage=profit_percentage,
                price_impact_percent=max(uniswap_price_impact, sushiswap_price_impact),
                execution_time_estimate=15.0,  # Estimated seconds for transaction
                uniswap_price=uniswap_data.price,
                sushiswap_price=sushiswap_reverse_price,
                price_difference_percent=price_diff_percent,
                liquidity_eth=min(uniswap_liquidity, sushiswap_liquidity),
                confidence_score=confidence_score,
                timestamp=time.time()
            )
            
            log_debug(f"Found opportunity: Path {path_info['id']}, {trade_amount_eth} ETH -> {net_profit_eth:.6f} ETH profit")
            return opportunity
            
        except Exception as e:
            log_error(f"Failed to calculate arbitrage for path {path_info['id']}", e)
            return None

class ArbitrageDetector:
    """Main arbitrage detection engine"""
    
    def __init__(self):
        self.calculator = ArbitrageCalculator()
        self.last_scan_time = 0
        self.opportunities_found = 0
    
    async def scan_for_opportunities(self) -> List[ArbitrageOpportunity]:
        """Scan all paths for arbitrage opportunities"""
        scan_start_time = time.time()
        all_opportunities = []
        
        try:
            log_debug("Starting arbitrage scan...")
            
            # Update gas price
            await self.calculator.gas_estimator.get_current_gas_price()
            
            # Get prices for all enabled paths
            all_prices = await price_manager.get_all_path_prices()
            
            if not all_prices:
                log_debug("No price data available for scanning")
                return []
            
            # Get enabled paths
            enabled_paths = settings.dynamic.get_enabled_paths()
            trade_amounts = settings.get_trade_amounts()
            
            log_debug(f"Scanning {len(enabled_paths)} paths with {len(trade_amounts)} trade amounts")
            
            # Check each path with each trade amount
            for path in enabled_paths:
                path_id = path['id']
                
                if path_id not in all_prices:
                    log_debug(f"No prices for path {path_id}")
                    continue
                
                prices = all_prices[path_id]
                
                # Test different trade amounts
                for trade_amount in trade_amounts:
                    opportunity = self.calculator.calculate_arbitrage_profit(
                        path, prices, trade_amount
                    )
                    
                    if opportunity:
                        all_opportunities.append(opportunity)
                        self.opportunities_found += 1
                        
                        # Log the opportunity
                        log_opportunity(
                            opportunity.path_id,
                            opportunity.path_name,
                            opportunity.net_profit_eth,
                            opportunity.net_profit_usd
                        )
                        
                        # Save to database
                        await self._save_opportunity_to_db(opportunity)
            
            # Sort by net profit (highest first)
            all_opportunities.sort(key=lambda x: x.net_profit_eth, reverse=True)
            
            scan_time = time.time() - scan_start_time
            log_info(f"Scan completed in {scan_time:.2f}s - Found {len(all_opportunities)} opportunities")
            
            self.last_scan_time = scan_time
            return all_opportunities
            
        except Exception as e:
            log_error("Failed to scan for opportunities", e)
            return []
    
    async def _save_opportunity_to_db(self, opportunity: ArbitrageOpportunity):
        """Save opportunity to database"""
        try:
            record = OpportunityRecord(
                path_id=opportunity.path_id,
                path_name=opportunity.path_name,
                profit_eth=opportunity.expected_profit_eth,
                profit_usd=opportunity.expected_profit_usd,
                trade_amount=opportunity.trade_amount_eth,
                gas_cost_eth=opportunity.gas_cost_eth,
                gas_cost_usd=opportunity.gas_cost_usd,
                net_profit_eth=opportunity.net_profit_eth,
                net_profit_usd=opportunity.net_profit_usd,
                uniswap_price=opportunity.uniswap_price,
                sushiswap_price=opportunity.sushiswap_price,
                price_diff_percent=opportunity.price_difference_percent,
                market_data=f'{{"confidence": {opportunity.confidence_score}, "price_impact": {opportunity.price_impact_percent}}}'
            )
            
            db.save_opportunity(record)
            
        except Exception as e:
            log_error("Failed to save opportunity to database", e)
    
    async def get_best_opportunities(self, limit: int = 5) -> List[ArbitrageOpportunity]:
        """Get the best current arbitrage opportunities"""
        opportunities = await self.scan_for_opportunities()
        return opportunities[:limit]
    
    def get_scan_stats(self) -> Dict:
        """Get scanning statistics"""
        return {
            'last_scan_time_seconds': self.last_scan_time,
            'total_opportunities_found': self.opportunities_found,
            'scanner_uptime': time.time() - (self.last_scan_time or time.time())
        }

# Global arbitrage detector instance
arbitrage_detector = ArbitrageDetector()