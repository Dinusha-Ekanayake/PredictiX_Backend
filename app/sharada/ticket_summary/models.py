from sqlalchemy import Column, Integer, Text, DateTime, String, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base

class TicketSummary(Base):
    __tablename__ = "ticket_summaries"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), index=True, nullable=False)

    summary_text = Column(Text, nullable=False)
    model_name = Column(String(100), nullable=False, default="sshleifer/distilbart-cnn-12-6")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)