import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool, NullPool

APP_ENV = os.getenv("APP_ENV", "local").lower()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./research_copilot.db")

if APP_ENV == "production" and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError("Production requires DATABASE_URL (Postgres), refusing to use SQLite.")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# Optimize for serverless/sleep mode
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
    )
else:
    # Production (Postgres): minimize idle connections for sleep mode
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        poolclass=QueuePool,
        pool_size=3,  # Keep only 3 connections in pool
        max_overflow=2,  # Allow 2 temporary connections
        pool_pre_ping=True,  # Test connections before reuse
        pool_recycle=300,  # Recycle connections every 5 minutes
        echo=False,
        echo_pool=False,
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()

