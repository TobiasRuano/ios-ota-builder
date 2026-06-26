"""Tests for tools/qr_svg.py."""

from __future__ import annotations

from qr_svg import matrix_to_svg, qr_matrix, qr_svg


def test_qr_matrix_is_square() -> None:
    matrix = qr_matrix("https://ota.example.com/install")
    size = len(matrix)
    assert size > 0
    assert all(len(row) == size for row in matrix)


def test_matrix_to_svg_contains_rects() -> None:
    matrix = [[True, False], [False, True]]
    svg = matrix_to_svg(matrix, module_px=2, quiet_zone=1)
    assert "<svg" in svg
    assert 'role="img"' in svg
    assert "<rect" in svg


def test_qr_svg_roundtrip() -> None:
    svg = qr_svg("hello")
    assert svg.startswith("<svg")
    assert "var(--qr-fg)" in svg
