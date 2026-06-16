from datetime import date


QUERIES = ("latest",)


def transform(records: list[dict], query: str) -> list[dict]:
    if query not in QUERIES:
        raise ValueError(f"Unknown transform query '{query}'. Supported: {', '.join(QUERIES)}")

    today = date.today().isoformat()
    filtered = [r for r in records if r.get("date", "") >= today]

    if query == "latest":
        by_kennel: dict[str, dict] = {}
        for r in filtered:
            kennel = r.get("kennel", "")
            if kennel not in by_kennel or r["date"] < by_kennel[kennel]["date"]:
                by_kennel[kennel] = r
        return sorted(by_kennel.values(), key=lambda r: r["date"])

    return filtered
