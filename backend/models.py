#This is only for demo pursoses, this will be replaced with a connection to a real database
from backend.db import Base 
from sqlalchemy import Column, Integer, Float, String, JSON, DateTime
from datetime import datetime

class CallCenterData(Base):
    __tablename__ = "call_center_data"

    id = Column(Integer, primary_key=True, index=True)

    incoming_calls = Column(Integer, nullable=False)
    answered_calls = Column(Integer, nullable=False)
    abandoned_calls = Column(Integer, nullable=False)

    answer_rate = Column(Float)          # stored as 94.01 (not 0.9401)
    service_level_20s = Column(Float)    # stored as 76.28

    answer_speed_avg = Column(Integer)   # seconds
    talk_duration_avg = Column(Integer)  # seconds
    waiting_time_avg = Column(Integer)   # seconds

class Users(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.now)

class Messages(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    conversation_id = Column(String, index=True)  
    messages = Column(JSON)  
    summary = Column(String)
    created_at = Column(DateTime, default=datetime.now)
