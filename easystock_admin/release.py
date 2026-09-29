"""Observable release identity for the admin health page.

The service must report an explicit deployment identity instead of implying
that the repository, VM and published frontend are the same build.
"""
import json
import os
from pathlib import Path


def identity() -> dict:
    values = {
        "release_id": os.environ.get("EASYSTOCK_RELEASE_ID", "").strip(),
        "source_commit": os.environ.get("EASYSTOCK_SOURCE_COMMIT", "").strip(),
        "channel": os.environ.get("EASYSTOCK_RELEASE_CHANNEL", "").strip(),
        "published_at": os.environ.get("EASYSTOCK_RELEASE_PUBLISHED_AT", "").strip(),
    }
    marker = Path(os.environ.get("EASYSTOCK_RELEASE_FILE", "/home/ubuntu/easystock/release-info.json"))
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in values:
                if not values[key] and isinstance(data.get(key), str):
                    values[key] = data[key].strip()
    except (OSError, ValueError, UnicodeError):
        pass
    values["identified"] = bool(values["release_id"] and values["source_commit"])
    return values
