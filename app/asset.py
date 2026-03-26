from sqlalchemy import Column, String, Text, Date, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from app.db.base import Base


class AssetCategory(Base):
    __tablename__ = "asset_categories"

    category_id = Column(Integer, primary_key=True, index=True)
    category_name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)


class Asset(Base):
    __tablename__ = "assets"

    asset_id = Column(Integer, primary_key=True, index=True)
    asset_code = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    category_id = Column(Integer, ForeignKey("asset_categories.category_id"), nullable=True)
    location = Column(String, nullable=True)
    asset_family = Column(String, nullable=True)

    status = Column(String, nullable=False)  # ACTIVE / INACTIVE / RETIRED
    criticality = Column(String, nullable=False)  # LOW / MEDIUM / HIGH / CRITICAL

    installation_date = Column(Date, nullable=True)
    health_score = Column(Integer, nullable=True)  # 0-100

    # Column name is "metadata" in DB, but attribute must NOT be "metadata" in SQLAlchemy
    metadata_ = Column("metadata", JSONB, nullable=False, server_default="{}")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
