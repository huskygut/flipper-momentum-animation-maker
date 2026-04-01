import io
import re
from functools import lru_cache

from PIL import Image, ImageOps


class BMEncoder:
    @staticmethod
    @lru_cache(maxsize=1)
    def _get_heatshrink_module():
        try:
            import heatshrink2
        except ImportError as exc:
            raise RuntimeError(
                "Export requires heatshrink2. Install it with: pip install heatshrink2"
            ) from exc
        return heatshrink2

    @classmethod
    def is_available(cls) -> bool:
        try:
            cls._get_heatshrink_module()
            return True
        except RuntimeError:
            return False

    @classmethod
    def convert_bm(cls, img: Image.Image) -> bytes:
        heatshrink2 = cls._get_heatshrink_module()

        with io.BytesIO() as output:
            # Use context managers so intermediate PIL images are closed
            # immediately rather than waiting for GC to release their buffers.
            with img.convert("1") as bm_img, ImageOps.invert(bm_img) as inv_img:
                inv_img.save(output, format="XBM")
            xbm = output.getvalue().decode(errors="ignore")

        try:
            hex_bytes = re.findall(r"0x([0-9a-fA-F]{2})", xbm)
            if not hex_bytes:
                raise ValueError("No XBM byte data found")
            raw_bytes = bytearray(int(byte, 16) for byte in hex_bytes)
        except Exception as exc:
            raise ValueError(f"Failed to parse XBM data: {exc}") from exc

        compressed_payload = bytearray(
            heatshrink2.compress(raw_bytes, window_sz2=8, lookahead_sz2=4)
        )

        # Guard: the 2-byte LE length field only holds 0–65535.  For the
        # Flipper's 128×64 screen the raw bitmap is 1 024 bytes so this can
        # never fire in practice, but be explicit rather than silently corrupt.
        if len(compressed_payload) > 0xFFFF:
            return b"\x00" + raw_bytes

        compressed = (
            bytearray([len(compressed_payload) & 0xFF, len(compressed_payload) >> 8])
            + compressed_payload
        )

        if len(compressed) + 2 < len(raw_bytes) + 1:
            return b"\x01\x00" + compressed
        return b"\x00" + raw_bytes