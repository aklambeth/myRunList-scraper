from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from generators.base_writer import BaseWriter

_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>myRunList</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    [x-cloak] {{ display: none; }}
  </style>
</head>
<body class="bg-gray-50 text-gray-900 min-h-screen p-6">
  <h1 class="text-2xl font-bold mb-6">Upcoming Runs</h1>
  <div id="app" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"></div>

  <script type="application/json" id="run-data">{data}</script>

  <script>
    (function () {{
      const payload = JSON.parse(document.getElementById('run-data').textContent);
      const records = payload.runs || [];
      const today = new Date().toISOString().slice(0, 10);

      // filter past, groupBy kennel → latest date
      const byKennel = {{}};
      for (const r of records) {{
        if (r.date < today) continue;
        if (!byKennel[r.kennel] || r.date > byKennel[r.kennel].date) {{
          byKennel[r.kennel] = r;
        }}
      }}

      const runs = Object.values(byKennel).sort((a, b) => a.date.localeCompare(b.date));
      const app = document.getElementById('app');

      if (runs.length === 0) {{
        app.innerHTML = '<p class="text-gray-500 col-span-full">No upcoming runs found.</p>';
        return;
      }}

      for (const r of runs) {{
        const loc = r.location || {{}};
        const locationParts = [loc.name, loc.address, loc.postcode].filter(Boolean);
        const locationStr = locationParts.length ? locationParts.join(', ') : null;
        const mapsUrl = (loc.lat && loc.lng)
          ? `https://www.google.com/maps?q=${{loc.lat}},${{loc.lng}}`
          : (loc.postcode ? `https://www.google.com/maps?q=${{encodeURIComponent(loc.postcode)}}` : null);
        const hares = (r.hares || []).join(', ');
        const websiteEl = r.website
          ? `<a href="${{r.website}}" target="_blank" rel="noopener" class="text-blue-600 hover:underline text-sm">Event page</a>`
          : '';
        const locationEl = locationStr
          ? (mapsUrl
              ? `<a href="${{mapsUrl}}" target="_blank" rel="noopener" class="hover:underline">${{locationStr}}</a>`
              : locationStr)
          : (mapsUrl ? `<a href="${{mapsUrl}}" target="_blank" rel="noopener" class="hover:underline">Map</a>` : '');
        const w3sEl = loc.w3s
          ? `<span class="text-gray-400 text-xs">///${{loc.w3s}}</span>`
          : '';

        const card = document.createElement('div');
        card.className = 'bg-white rounded-xl shadow-sm border border-gray-200 p-5 flex flex-col gap-2';
        card.innerHTML = `
          <div class="flex items-start justify-between gap-2">
            <div>
              <p class="font-semibold text-lg leading-tight">${{r.name}}</p>
              <p class="text-gray-500 text-sm">Run #${{r.runno}}</p>
            </div>
            ${{websiteEl ? `<div>${{websiteEl}}</div>` : ''}}
          </div>
          <div class="text-sm text-gray-700 flex flex-col gap-1">
            <p><span class="font-medium">Date:</span> ${{r.date}}${{r.time ? ' at ' + r.time : ''}}</p>
            ${{locationEl ? `<p><span class="font-medium">Location:</span> ${{locationEl}}</p>` : ''}}
            ${{w3sEl ? `<p>${{w3sEl}}</p>` : ''}}
            ${{r.oninn ? `<p><span class="font-medium">On-in:</span> ${{r.oninn}}</p>` : ''}}
            ${{hares ? `<p><span class="font-medium">Hares:</span> ${{hares}}</p>` : ''}}
            ${{r.notes ? `<p class="text-gray-500 text-xs mt-1">${{r.notes}}</p>` : ''}}
          </div>
        `;
        app.appendChild(card);
      }}
    }})();
  </script>
</body>
</html>
"""


class HTMLWriter(BaseWriter):
    def write(self, records: list[dict], dest: Optional[Path]) -> None:
        data = json.dumps({"$schema": "https://raw.githubusercontent.com/aklambeth/myRunList-scraper/main/schemas/run.schema.json", "runs": records}, indent=2)
        output = _TEMPLATE.format(data=data)
        if dest is None:
            sys.stdout.write(output)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(output, encoding="utf-8")
