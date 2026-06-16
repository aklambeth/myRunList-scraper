from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from generators.base_writer import BaseWriter

SCHEMA_URI = "https://raw.githubusercontent.com/aklambeth/myRunList-scraper/main/schemas/run.schema.json"


class JSONWriter(BaseWriter):
    def write(self, records: list[dict], dest: Optional[Path]) -> None:
        payload = {"$schema": SCHEMA_URI, "runs": records}
        output = json.dumps(payload, indent=2)
        if dest is None:
            sys.stdout.write(output + "\n")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(output + "\n", encoding="utf-8")
