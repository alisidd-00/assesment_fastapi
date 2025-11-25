import os
from sqlalchemy import create_engine, Column, String, Integer, DateTime, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./drive.db")


if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class BlobMetadata(Base):
    __tablename__ = "blobs_metadata"

    id = Column(String, primary_key=True, index=True)
    size = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    storage_type = Column(String)  


class BlobDataStore(Base):
    __tablename__ = "blobs_data"

    id = Column(String, primary_key=True, index=True)
    data = Column(LargeBinary)  