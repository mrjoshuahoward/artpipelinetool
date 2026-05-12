from __future__ import annotations
from pathlib import Path
from typing import Optional


def check_file_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


def check_dimensions(path: Path, expected: list[int]) -> Optional[bool]:
    try:
        from PIL import Image
        with Image.open(path) as img:
            return list(img.size) == list(expected)
    except ImportError:
        return None
    except OSError:
        return False


def check_has_alpha(path: Path) -> Optional[bool]:
    try:
        from PIL import Image
        with Image.open(path) as img:
            return img.mode in ("RGBA", "LA", "PA")
    except ImportError:
        return None
    except OSError:
        return False


def run_checks(file_path: Path, expected_dimensions: list[int], asset_type: str = None) -> dict:
    exists = check_file_exists(file_path)
    # app_icon assets must NOT have alpha (App Store requirement).
    # mockup assets are PNG design references, not production files — alpha is irrelevant.
    check_alpha = exists and asset_type not in ("app_icon", "mockup")
    return {
        "file_exists": exists,
        "dimensions_correct": check_dimensions(file_path, expected_dimensions) if exists else None,
        "has_alpha": check_has_alpha(file_path) if check_alpha else None,
    }
