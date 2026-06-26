"""Generate inline SVG QR codes without external pip dependencies."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qrcodegen import QrCode


def qr_matrix(text: str) -> list[list[bool]]:
    """Return a square QR module matrix for the given UTF-8 text."""
    qr = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
    size = qr.get_size()
    return [[qr.get_module(x, y) for x in range(size)] for y in range(size)]


def matrix_to_svg(
    matrix: list[list[bool]],
    *,
    module_px: int = 4,
    quiet_zone: int = 4,
) -> str:
    """Render a module matrix as an inline SVG string."""
    size = len(matrix)
    total_modules = size + quiet_zone * 2
    view = total_modules * module_px
    rects: list[str] = []
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if not dark:
                continue
            px = (x + quiet_zone) * module_px
            py = (y + quiet_zone) * module_px
            rects.append(
                f'<rect x="{px}" y="{py}" width="{module_px}" height="{module_px}" fill="var(--text)"/>'
            )
    rect_markup = "\n    ".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" '
        f'role="img" aria-label="QR code" width="{view}" height="{view}">\n'
        f'  <rect width="{view}" height="{view}" fill="var(--surface)"/>\n'
        f"    {rect_markup}\n"
        f"</svg>"
    )


def qr_svg(text: str, *, module_px: int = 4, quiet_zone: int = 4) -> str:
    """Encode text as an inline SVG QR code."""
    return matrix_to_svg(qr_matrix(text), module_px=module_px, quiet_zone=quiet_zone)
