_TOPIC_TERMS: list[tuple[str, str]] = [
    ("ptp", "ptp"),
    ("precision time protocol", "ptp"),
    ("gnss", "gnss"),
    ("gps", "gnss"),
    ("synce", "synce"),
    ("synchronous ethernet", "synce"),
    ("ntp", "ntp"),
    ("1pps", "1pps"),
    ("one pulse per second", "1pps"),
    ("white rabbit", "white rabbit"),
    ("open timecard", "open timecard"),
    ("clock quorum", "clock quorum"),
    ("open time server", "open time server"),
    ("vgmc", "vgmc"),
    ("grandmaster", "grandmaster"),
    ("pricing", "pricing"),
    ("compliance", "compliance"),
    ("onboarding", "onboarding"),
    ("objection", "objection"),
    ("sequence", "sequence"),
    ("abm", "abm"),
    ("stl", "stl"),
    ("galileo", "gnss"),
    ("5g", "5g"),
    ("defence", "defence"),
    ("defense", "defence"),
    ("hft", "hft"),
    ("trading", "hft"),
]

MAX_TOPICS = 3


def extract_topics(message: str) -> list[str]:
    normalised = message.lower()
    seen: set[str] = set()
    results: list[str] = []
    for keyword, label in _TOPIC_TERMS:
        if label in seen:
            continue
        if keyword in normalised:
            seen.add(label)
            results.append(label)
        if len(results) >= MAX_TOPICS:
            break
    return results
