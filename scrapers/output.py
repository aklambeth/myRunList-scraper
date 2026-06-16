"""Data output and archiving for SSG consumption."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

_DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


class OutputWriter:
    def __init__(self, archive_retention_days: int = 365, root: Path = _DATA_ROOT):
        self.archive_retention_days = archive_retention_days
        self.root = Path(root)

    def _output_path(self, site: str) -> Path:
        return self.root / f"{site}.json"

    def _archive_dir(self, site: str) -> Path:
        return self.root / "archive" / site

    def write(self, site: str, records: list[dict]) -> Path:
        """Archive existing output, write new output, purge old archives."""
        self.root.mkdir(parents=True, exist_ok=True)
        out_path = self._output_path(site)

        if out_path.exists():
            self._archive(site, out_path)

        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2)
            fh.write("\n")

        self._purge_archives(site)
        return out_path

    def _archive(self, site: str, out_path: Path) -> None:
        archive_dir = self._archive_dir(site)
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        dest = archive_dir / f"{site}_{ts}.json"
        dest.write_bytes(out_path.read_bytes())

    def _purge_archives(self, site: str) -> None:
        archive_dir = self._archive_dir(site)
        if not archive_dir.exists():
            return
        cutoff = datetime.now() - timedelta(days=self.archive_retention_days)
        for f in archive_dir.glob(f"{site}_*.json"):
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
