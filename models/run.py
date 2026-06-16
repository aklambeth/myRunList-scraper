"""Pydantic models matching schemas/run.schema.json.

Scrapers build records via these models and emit clean dicts with
``model_dump(exclude_none=True)`` so optional fields are omitted rather than
written as ``null``.
"""

import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

OSGRID_PATTERN = r"^[A-Z]{2}[0-9]{4}([0-9]{2}([0-9]{2}([0-9]{2})?)?)?$"
W3S_PATTERN = r"^[a-z]+\.[a-z]+\.[a-z]+$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
TIME_PATTERN = r"^\d{2}:\d{2}$"


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    address: Optional[str] = None
    postcode: Optional[str] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    osgrid: Optional[str] = Field(default=None, pattern=OSGRID_PATTERN)
    w3s: Optional[str] = Field(default=None, pattern=W3S_PATTERN)


class Run(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    runno: int = Field(gt=0)
    date: str = Field(pattern=DATE_PATTERN)
    time: Optional[str] = Field(default=None, pattern=TIME_PATTERN)
    location: Location = Field(default_factory=Location)
    oninn: Optional[str] = None
    hares: Optional[List[str]] = Field(default=None, min_length=1)
    notes: Optional[str] = None
    website: Optional[str] = None

    @field_validator("hares")
    @classmethod
    def _strip_empty_hares(cls, v):
        if v is None:
            return None
        cleaned = [h.strip() for h in v if h and h.strip()]
        return cleaned or None

    def to_record(self) -> dict:
        """Schema-conformant dict with optional/None fields omitted."""
        return self.model_dump(exclude_none=True)
