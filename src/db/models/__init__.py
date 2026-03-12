"""
DB models package.

Importing this package registers all model classes with Base.metadata.
Used by src/db/alembic/env.py to populate target_metadata for autogenerate.
"""
from .base import Base
from .cvm import CVMRecord
from .bacen import SGSObservation, PTAXRate
from .b3_calc import B3Security, B3PricingSnapshot

__all__ = [
    "Base",
    "CVMRecord",
    "SGSObservation",
    "PTAXRate",
    "B3Security",
    "B3PricingSnapshot",
]
