import uuid
from sqlalchemy import Boolean, Column, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from app.db.base import Base

class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    contact_no = Column(String)
    password_hash = Column(Text, nullable=False)
    role = Column(String, nullable=False)  # ADMIN / USER
    dept_id = Column(ForeignKey("departments.dept_id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    warehouse = Column(String)

