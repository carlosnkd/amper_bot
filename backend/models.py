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

class AgentTraces(Base):
    """
    One row per intermediate agent DECISION, not per response -- e.g. "REVIEWER rejected,
    here's the 1-2 sentence why", never the full chat/build output (that's what `messages`
    is for). Rows are tagged with `turn_id`, which ties every step belonging to one chat
    turn together -- INTENT (+ROUTER for a direct CHAT/SNIPPET reply) for every message,
    or INTENT + PLANNER + CODER/REVIEWER (repeated per retry) + SYSTEM for a TICKET whose
    plan gets approved and built. The same turn_id is reused across the /run -> /build
    lifecycle for one ticket (see backend/cache/plan_cache.py and
    backend/services/research.py) so a build's steps land in the same group as the plan
    that produced it, even though they arrive in a separate HTTP request. See
    agents/ticket_pipeline/flow.py's TicketState.trace for what populates a step, and
    backend/services/chat.py's record_trace()/get_trace() for how rows here get grouped
    back into turns. Never shown in the chat transcript itself -- only surfaced on demand
    via GET /trace.
    """
    __tablename__ = "agent_traces"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    conversation_id = Column(String, index=True)
    turn_id = Column(String, index=True)
    agent = Column(String)      # "INTENT" | "PLANNER" | "CODER" | "REVIEWER" | "ROUTER" | "SYSTEM"
    decision = Column(String)   # short label, e.g. "TICKET", "approved", "max_retries_reached"
    reasoning = Column(String)  # 1-2 sentence why -- never the full agent output
    # ISO timestamp string set by the step's own recorder (flow.py/research.py), not a DB
    # default -- steps are often appended to an in-memory list during a run and only
    # batch-persisted afterward, so "when the row was inserted" would lose real ordering.
    timestamp = Column(String)
