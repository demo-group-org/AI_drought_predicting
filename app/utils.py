from difflib import SequenceMatcher


def match_zone_to_location(location_text, zones):
    """Best-effort match of a farmer's free-text location (e.g. from signup)
    to one of the known Zone rows, so forms can pre-select it automatically."""
    if not location_text:
        return None
    location_text = location_text.strip().lower()
    best_id, best_score = None, 0.0
    for z in zones:
        score = SequenceMatcher(None, location_text, z.name.lower()).ratio()
        if location_text in z.name.lower() or z.name.lower() in location_text:
            score = max(score, 0.9)
        if score > best_score:
            best_score, best_id = score, z.id
    return best_id if best_score >= 0.5 else None
