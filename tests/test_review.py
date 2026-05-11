import pytest
from pathlib import Path
from artpipeline import review


def test_file_exists_true(tmp_path):
    f = tmp_path / "img.png"
    f.write_bytes(b"fake")
    assert review.check_file_exists(f) is True


def test_file_exists_false(tmp_path):
    assert review.check_file_exists(tmp_path / "missing.png") is False


def test_run_checks_missing_file(tmp_path):
    result = review.run_checks(tmp_path / "missing.png", [48, 48])
    assert result["file_exists"] is False
    assert result["dimensions_correct"] is None
    assert result["has_alpha"] is None


def test_run_checks_existing_png(tmp_path):
    # Create a minimal valid 48x48 RGBA PNG using Pillow
    pytest.importorskip("PIL")
    from PIL import Image
    img_path = tmp_path / "test.png"
    img = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    img.save(img_path)
    result = review.run_checks(img_path, [48, 48])
    assert result["file_exists"] is True
    assert result["dimensions_correct"] is True
    assert result["has_alpha"] is True


def test_run_checks_wrong_dimensions(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    img_path = tmp_path / "test.png"
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    img.save(img_path)
    result = review.run_checks(img_path, [48, 48])
    assert result["dimensions_correct"] is False


def test_run_checks_no_alpha(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    img_path = tmp_path / "test.png"
    img = Image.new("RGB", (48, 48), (255, 255, 255))
    img.save(img_path)
    result = review.run_checks(img_path, [48, 48])
    assert result["has_alpha"] is False
