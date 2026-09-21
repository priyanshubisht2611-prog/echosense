import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .models import Base, Detection, Device, DetectionHourly, DetectionDaily, DetectionWeekly, DetectionMonthly

# This ensures the database file goes into the /data folder relative to the project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'data', 'echosense.db')}"

# Create engine with SQLite
# check_same_thread=False is needed for FastAPI's async nature
# WAL mode improves concurrent read access
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Enable WAL mode for better concurrency
with engine.connect() as conn:
    conn.execute(text("PRAGMA journal_mode=WAL"))
    conn.execute(text("PRAGMA synchronous=NORMAL"))

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()