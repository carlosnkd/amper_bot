#This is only for demo pursoses, this will be replaced with a connection to a real database
from backend.db import Base
from sqlalchemy import Column, Integer, Float, String, JSON, DateTime
from datetime import datetime

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
