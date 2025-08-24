import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
import sys

class ScannerLogger:
    def __init__(self, name="DexesScanner"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Create logs directory if it doesn't exist
        if not os.path.exists('logs'):
            os.makedirs('logs')
        
        # Clear existing handlers to avoid duplicates
        self.logger.handlers.clear()
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | %(message)s'
        )
        simple_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s'
        )
        
        # Console handler (for development) - Fixed for Windows Unicode
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
        
        # Fix encoding issues on Windows
        if sys.platform.startswith('win'):
            try:
                console_handler.stream.reconfigure(encoding='utf-8', errors='replace')
            except:
                pass  # Fallback for older Python versions
        
        self.logger.addHandler(console_handler)
        
        # File handler - General logs
        file_handler = RotatingFileHandler(
            'logs/scanner.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        self.logger.addHandler(file_handler)
        
        # File handler - Trade logs
        trade_handler = RotatingFileHandler(
            'logs/trades.log',
            maxBytes=5*1024*1024,   # 5MB
            backupCount=3
        )
        trade_handler.setLevel(logging.INFO)
        trade_handler.setFormatter(detailed_formatter)
        
        # File handler - Error logs
        error_handler = RotatingFileHandler(
            'logs/errors.log',
            maxBytes=5*1024*1024,   # 5MB
            backupCount=3
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)
        self.logger.addHandler(error_handler)
    
    def _clean_message(self, message):
        """Clean message of problematic Unicode characters for Windows"""
        if sys.platform.startswith('win'):
            # Replace emoji characters with ASCII equivalents
            replacements = {
                '🧪': '[TEST]', '✅': '[OK]', '❌': '[ERROR]', '⚠️': '[WARNING]',
                '🔍': '[SCAN]', '💰': '[PROFIT]', '🌐': '[WEB3]', '💾': '[DB]',
                '📋': '[CONFIG]', '🎯': '[TARGET]', '⛽': '[GAS]', '📊': '[STATS]',
                '🚀': '[START]', 'ℹ️': '[INFO]', '💡': '[TIP]', '🔄': '[REFRESH]',
                '🎉': '[SUCCESS]', '🛑': '[STOP]', '📈': '[UP]', '📉': '[DOWN]'
            }
            for emoji, replacement in replacements.items():
                message = message.replace(emoji, replacement)
        return message
    
    def info(self, message, extra_data=None):
        """Log info message with optional extra data"""
        message = self._clean_message(str(message))
        if extra_data:
            message = f"{message} | Data: {extra_data}"
        self.logger.info(message)
    
    def warning(self, message, extra_data=None):
        """Log warning message"""
        message = self._clean_message(str(message))
        if extra_data:
            message = f"{message} | Data: {extra_data}"
        self.logger.warning(message)
    
    def error(self, message, error=None, extra_data=None):
        """Log error message with exception details"""
        message = self._clean_message(str(message))
        if error:
            message = f"{message} | Error: {str(error)}"
        if extra_data:
            message = f"{message} | Data: {extra_data}"
        self.logger.error(message, exc_info=True if error else False)
    
    def debug(self, message, extra_data=None):
        """Log debug message"""
        message = self._clean_message(str(message))
        if extra_data:
            message = f"{message} | Data: {extra_data}"
        self.logger.debug(message)
    
    def trade_log(self, path_id, profit_eth, gas_cost, status, extra_data=None):
        """Specialized logging for trade events"""
        trade_msg = f"TRADE | Path: {path_id} | Profit: {profit_eth:.6f} ETH | Gas: ${gas_cost:.2f} | Status: {status}"
        if extra_data:
            trade_msg = f"{trade_msg} | {extra_data}"
        
        # Log to both general and trade-specific log
        self.logger.info(trade_msg)
        
        # Create separate trade logger for trades.log
        trade_logger = logging.getLogger(f"{self.logger.name}.trades")
        if not trade_logger.handlers:
            trade_handler = RotatingFileHandler(
                'logs/trades.log',
                maxBytes=5*1024*1024,
                backupCount=3
            )
            trade_handler.setFormatter(logging.Formatter(
                '%(asctime)s | %(message)s'
            ))
            trade_logger.addHandler(trade_handler)
            trade_logger.setLevel(logging.INFO)
        
        trade_logger.info(trade_msg)
    
    def opportunity_log(self, path_id, description, profit_eth, profit_usd):
        """Log arbitrage opportunities"""
        opp_msg = f"OPPORTUNITY | Path {path_id}: {description} | Profit: {profit_eth:.6f} ETH (${profit_usd:.2f})"
        self.info(opp_msg)
    
    def startup_log(self):
        """Log scanner startup"""
        self.info("=" * 60)
        self.info("[START] DEXES SCANNER STARTING UP")
        self.info("=" * 60)
    
    def shutdown_log(self):
        """Log scanner shutdown"""
        self.info("=" * 60)
        self.info("[STOP] DEXES SCANNER SHUTTING DOWN")
        self.info("=" * 60)

# Global logger instance
logger = ScannerLogger()

# Convenience functions for easy imports
def log_info(message, extra_data=None):
    logger.info(message, extra_data)

def log_warning(message, extra_data=None):
    logger.warning(message, extra_data)

def log_error(message, error=None, extra_data=None):
    logger.error(message, error, extra_data)

def log_debug(message, extra_data=None):
    logger.debug(message, extra_data)

def log_trade(path_id, profit_eth, gas_cost, status, extra_data=None):
    logger.trade_log(path_id, profit_eth, gas_cost, status, extra_data)

def log_opportunity(path_id, description, profit_eth, profit_usd):
    logger.opportunity_log(path_id, description, profit_eth, profit_usd)