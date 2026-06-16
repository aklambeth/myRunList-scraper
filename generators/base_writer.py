from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class BaseWriter(ABC):
    @abstractmethod
    def write(self, records: list[dict], dest: Optional[Path]) -> None:
        """Write records to dest file, or stdout if dest is None."""
