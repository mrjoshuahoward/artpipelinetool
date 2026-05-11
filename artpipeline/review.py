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


def check_has_alpha(path: Path) -> Optional[bool]:
    try:
        from PIL import Image
        with Image.open(path) as img:
            return img.mode in ("RGBA", "LA", "PA")
    except ImportError:
        return None


def run_checks(filed_path: Path, expected_dimensions: list[int]) -> dict:
    exists = check_file_exists(filed_path)
    return {
        "file_exists": exists,
        "dimensions_correct": check_dimensions(filed_path, expected_dimensions) if exists else None,
        "has_alpha": check_has_alpha(filed_path) if exists else None,
    }
