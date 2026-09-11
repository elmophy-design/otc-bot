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
