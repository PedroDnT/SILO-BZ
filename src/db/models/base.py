"""
Shared DeclarativeBase for all schema models.

All ORM model classes import Base from here. A single Base ensures
Alembic's target_metadata captures tables from all three schemas
(cvm, bacen, b3_calc) in one `alembic upgrade head` run.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
