from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from generators.base_writer import BaseWriter

_TEMPLATE_PATH = Path(__file__).parent.parent / "template.html"
_PLACEHOLDER = "__RUN_DATA__"


class HTMLWriter(BaseWriter):
    def write(self, records: list[dict], dest: Optional[Path]) -> None:
        data = json.dumps({"$schema": "https://raw.githubusercontent.com/aklambeth/myRunList-scraper/main/schemas/run.schema.json", "runs": records}, indent=2)
        output = _TEMPLATE_PATH.read_text(encoding="utf-8").replace(_PLACEHOLDER, data)
        if dest is None:
            sys.stdout.write(output)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(output, encoding="utf-8")
