"""Database Schemas"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    """User Model"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String(50), unique=True, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    last_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)

class SignalHistory(Base):
    """Signal History Model"""
    __tablename__ = 'signal_history'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    asset = Column(String(50))
    action = Column(String(10))
    confidence = Column(Float)
    entry_price = Column(Float)
    signal_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


class TradeHistory(Base):
    """Executed trade outcomes (separate from generated-signal history).

    A row is created only when place_trade() actually succeeds against
    a real broker connection (BotV2). Resolved WIN/LOSS by check_win()
    once the expiry has passed, then pushed to the user on Telegram.
    """
    __tablename__ = 'trade_history'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    telegram_id = Column(String(50))
    chat_id = Column(String(50))
    asset = Column(String(50))
    direction = Column(String(10))
    amount = Column(Float)
    duration_secs = Column(Integer)
    order_id = Column(String(100))
    entry_price = Column(Float, nullable=True)
    placed_at = Column(DateTime, default=datetime.utcnow)
    expiry_at = Column(DateTime, nullable=True)
    result = Column(String(24), default="PENDING")  # PENDING | SETTLING | WIN | LOSS | DRAW | UNKNOWN | REQUIRES_RECONCILIATION
    payout = Column(Float, nullable=True)
    profit_loss = Column(Float, nullable=True)
    broker_result = Column(String(100), nullable=True)
    settlement_source = Column(String(50), nullable=True)
    settlement_attempts = Column(Integer, default=0)
    last_settlement_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    notified = Column(Integer, default=0)  # 0/1 - has the Telegram push been sent
