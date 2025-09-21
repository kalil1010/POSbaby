from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Date, Numeric
from sqlalchemy.orm import sessionmaker, declarative_base

from settings import DATABASE_URL

# Create a SQLAlchemy engine and base class
engine = create_engine(DATABASE_URL, echo=True)
metadata = MetaData()
Base = declarative_base(metadata=metadata)

# Session factory – we will use this everywhere
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
