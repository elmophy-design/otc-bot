"""
Configuration manager for OTC Signal Bot
File: config/settings.py
"""
import os
import yaml
from pathlib import Path
from typing import Optional, Dict, List, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    """Main configuration manager"""
    
    def __init__(self, env: Optional[str] = None, require_token: bool = True):
        self.env = env or os.getenv('ENV', 'development')
        self.config_dir = Path(__file__).parent
        self._load_config()
        self._load_environment(require_token)
    
    def _load_config(self):
        """Load YAML configuration"""
        config_file = self.config_dir / f"{self.env}.yaml"
        if not config_file.exists():
            # Create default config if not exists
            self.config = {
                'api': {
                    'pocketoption': {
                        'ws_url': 'wss://ws.pocketoption.com',
                        'http_url': 'https://api.pocketoption.com'
                    }
                },
                'assets': {
                    'otc_list': [
                        'EURUSD_otc', 'GBPUSD_otc', 'USDJPY_otc',
                        'XAUUSD_otc', 'BTCUSD_otc', 'ETHUSD_otc'
                    ]
                }
            }
            return
            
        with open(config_file, 'r') as f:
            self.config = yaml.safe_load(f) or {}
    
    def _load_environment(self, require_token: bool = True):
        """Load environment variables"""
        
        # Telegram
        self.TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
        if require_token and not self.TELEGRAM_BOT_TOKEN:
            print("⚠️ TELEGRAM_BOT_TOKEN not found in .env file")
        
        # PocketOption SSID - Try multiple names
        self.POCKET_SSID = os.getenv('POCKET_SSID')
        self.SSID = self.POCKET_SSID
        self.POCKETOPTION_SSID = os.getenv('POCKETOPTION_SSID') or self.POCKET_SSID
        
        # PocketOption User ID
        self.POCKET_USER_ID = os.getenv('POCKET_USER_ID')
        self.USER_ID = self.POCKET_USER_ID
        self.POCKETOPTION_USER_ID = os.getenv('POCKETOPTION_USER_ID') or self.POCKET_USER_ID
        
        # Database
        self.DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/bot.db')
        
        # Redis
        self.REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        
        # Debug
        self.DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
        
        # Signal settings
        signal_config = self.config.get('signals', {})
        self.MIN_CONFIDENCE = int(os.getenv('MIN_CONFIDENCE', signal_config.get('min_confidence', 70)))
        self.USE_AI = os.getenv('USE_AI', str(signal_config.get('use_ai', False))).lower() == 'true'
        self.TECH_WEIGHT = float(os.getenv('TECH_WEIGHT', signal_config.get('tech_weight', 0.6)))
        
        # Trading
        trading_config = self.config.get('trading', {})
        self.DEMO_MODE = os.getenv('DEMO_MODE', 'true').lower() == 'true'
        self.MAX_TRADE_AMOUNT = float(os.getenv('MAX_TRADE_AMOUNT', trading_config.get('max_trade_amount', 10.0)))
        self.MIN_TRADE_AMOUNT = float(os.getenv('MIN_TRADE_AMOUNT', trading_config.get('min_trade_amount', 1.0)))
        self.DEFAULT_TRADE_AMOUNT = float(os.getenv('DEFAULT_TRADE_AMOUNT', self.MIN_TRADE_AMOUNT))
        # Display timezone for signal timestamps (WAT = Africa/Lagos)
        self.DISPLAY_TIMEZONE = os.getenv(
            'DISPLAY_TIMEZONE',
            trading_config.get('display_timezone', 'Africa/Lagos'),
        )
        self.DEFAULT_TIMEFRAME = os.getenv(
            'DEFAULT_TIMEFRAME',
            trading_config.get('default_timeframe', '1m'),
        )
        self.DEFAULT_EXPIRY = int(
            os.getenv('DEFAULT_EXPIRY', trading_config.get('default_expiry', 60))
        )
        
        # Assets
        self.OTC_ASSETS = self.config.get('assets', {}).get('otc_list', [])
        if not self.OTC_ASSETS:
            self.OTC_ASSETS = [
                "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc",
                "AUDUSD_otc", "USDCAD_otc", "NZDUSD_otc",
                "XAUUSD_otc", "XAGUSD_otc",
                "BTCUSD_otc", "ETHUSD_otc"
            ]
        
        # API URLs
        api_config = self.config.get('api', {}).get('pocketoption', {})
        self.API_WS_URL = api_config.get('ws_url', 'wss://ws.pocketoption.com')
        self.API_HTTP_URL = api_config.get('http_url', 'https://api.pocketoption.com')
        self.API_RECONNECT_ATTEMPTS = int(api_config.get('reconnect_attempts', 5))
        self.API_TIMEOUT = int(api_config.get('timeout', 30))
    
    def get_ssid(self) -> Optional[str]:
        """Get SSID from any source"""
        sources = [
            self.POCKET_SSID,
            self.SSID,
            self.POCKETOPTION_SSID,
            os.getenv('POCKET_SSID'),
            os.getenv('POCKETOPTION_SSID'),
            os.getenv('SSID'),
        ]
        for source in sources:
            if source and len(str(source)) > 10:
                return str(source)
        return None
    
    def get_user_id(self) -> Optional[str]:
        """Get User ID from any source"""
        sources = [
            self.POCKET_USER_ID,
            self.USER_ID,
            self.POCKETOPTION_USER_ID,
            os.getenv('POCKET_USER_ID'),
            os.getenv('POCKETOPTION_USER_ID'),
            os.getenv('USER_ID'),
        ]
        for source in sources:
            if source:
                return str(source)
        return None

# Singleton
_settings = None

def get_settings(env: Optional[str] = None, require_token: bool = True) -> Settings:
    """Get settings instance"""
    global _settings
    if _settings is None:
        _settings = Settings(env, require_token)
    return _settings

# Test function
def test_ssid():
    """Test SSID loading"""
    settings = get_settings(require_token=False)
    ssid = settings.get_ssid()
    user_id = settings.get_user_id()
    
    print("=" * 50)
    print("📊 POCKETOPTION SSID STATUS")
    print("=" * 50)
    print(f"SSID Length: {len(ssid) if ssid else 0}")
    print(f"SSID Preview: {repr(ssid[:50]) if ssid else 'None'}")
    print(f"User ID: {user_id if user_id else 'Not found'}")
    print("=" * 50)
    
    if ssid:
        print("✅ SSID FOUND! Ready to connect.")
    else:
        print("❌ SSID NOT FOUND!")
        print("\nPlease add to .env file:")
        print("POCKET_SSID=your_ssid_here")
        print("POCKET_USER_ID=your_user_id_here")
    
    return ssid

if __name__ == "__main__":
    test_ssid()