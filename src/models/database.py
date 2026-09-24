"""Database Management"""
from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from config.settings import get_settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """Professional Database Manager with Connection Pooling"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.settings = get_settings(require_token=False)
        db_url = self.settings.DATABASE_URL

        if db_url.startswith("sqlite:///"):
            path = db_url.replace("sqlite:///", "", 1)
            if not os.path.isabs(path):
                path = os.path.abspath(path)
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)

        self.engine = create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
        self.SessionFactory = sessionmaker(bind=self.engine)
        self._initialized = True
        logger.info(f"Database initialized: {db_url}")

    def get_session(self) -> Session:
        """Get database session"""
        return self.SessionFactory()

    def create_tables(self, base):
        """Create all tables"""
        base.metadata.create_all(self.engine)
        logger.info("Tables created")
