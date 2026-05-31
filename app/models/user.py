import uuid
from sqlalchemy import Column, String, Date
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class User(Base):
    __tablename__ = "AddUser"

    user_id            = Column("User ID", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name         = Column("First Name", String, nullable=False)
    last_name          = Column("Last Name", String, nullable=False)
    email              = Column("Email Address", String, nullable=True)
    role               = Column("Role", String, nullable=True, default="USER")
    status             = Column("Status", String, nullable=True, default="active")
    department         = Column("Department", String, nullable=True)
    residence_address  = Column("Residence Address", String, nullable=True)
    contact_no         = Column("Contact Number", String, nullable=True)
    warehouse          = Column("Warehouse", String, nullable=True)
    created_at         = Column("Created_at", Date, nullable=True)