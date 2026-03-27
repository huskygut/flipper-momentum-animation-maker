from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageSequence

from constants import PREVIEW_BG, PREVIEW_FG, PREVIEW_SIZE, WIDTH, HEIGHT
from utils import sanitize_name

_CACHE_MAX = 256  # Maximum processed frames to keep in memory


class ImageProcessor:
    def __init__(self, fit_mode_getter, threshold_getter, contrast_getter):
        self.fit_mode_getter = fit_mode_getter
        self.threshold_getter = threshold_getter
        self.contrast_getter = contrast_getter
        # OrderedDict used as a simple LRU: recently used entries are moved
        # to the end; the oldest entry is evicted one-at-a-time when the limit
        # is reached — avoiding the "clear everything at once" stall of the
        # previous dict implementation.
        # Key: (id(img), threshold, WIDTH, contrast, fit_mode).
        # id(img) is safe here because all source frames live in all_frames
        # for the full lifetime of the loaded GIF, preventing address reuse.
        self._processed_cache: OrderedDict[tuple, Image.Image] = OrderedDict()

    def clear_cache(self) -> None:
        self._processed_cache.clear()

    def load_gif_frames(self, path: str) -> list[Image.Image]:
        self.clear_cache()
        with Image.open(path) as img:
            if getattr(img, "n_frames", 1) <= 0:
                return []
            return [frame.copy().convert("RGBA") for frame in ImageSequence.Iterator(img)]

    def suggest_animation_name(self, path: str) -> str:
        return sanitize_name(Path(path).stem, "animation")

    def estimate_memory_mb(self, frames: list[Image.Image]) -> float:
        total_bytes = sum(
            frame.width * frame.height * len(frame.getbands())
            for frame in frames
        )
        return total_bytes / (1024 * 1024)

    def fit_image(self, img: Image.Image) -> Image.Image:
        with img.convert("RGBA") as src:
            if src.width <= 0 or src.height <= 0:
                raise ValueError("Cannot fit an image with zero width or height.")

            with Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 255)) as bg:
                if self.fit_mode_getter() == "cover":
                    scale = max(WIDTH / src.width, HEIGHT / src.height)
                else:
                    scale = min(WIDTH / src.width, HEIGHT / src.height)

                new_size = (
                    max(1, int(round(src.width * scale))),
                    max(1, int(round(src.height * scale))),
                )
                with src.resize(new_size, Image.LANCZOS) as resized:
                    x = (WIDTH - resized.width) // 2
                    y = (HEIGHT - resized.height) // 2
                    bg.paste(resized, (x, y), resized)
                return bg.convert("RGB")

    def process_frame(self, img: Image.Image) -> Image.Image:
        cache_key = (
            id(img),
            max(0, min(255, int(self.threshold_getter()))),
            WIDTH,
            round(max(0.1, float(self.contrast_getter())), 2),
            str(self.fit_mode_getter()),
        )

        # LRU hit: move to end (most-recently-used) and return a copy.
        if cache_key in self._processed_cache:
            self._processed_cache.move_to_end(cache_key)
            return self._processed_cache[cache_key].copy()

        fitted = self.fit_image(img)
        gray = fitted.convert("L")
        contrast = max(0.1, float(self.contrast_getter()))
        gray = ImageEnhance.Contrast(gray).enhance(contrast)
        threshold = max(0, min(255, int(self.threshold_getter())))
        processed = gray.point(lambda p: 255 if p > threshold else 0, mode="1")

        # Evict the single oldest entry rather than clearing the whole cache.
        if len(self._processed_cache) >= _CACHE_MAX:
            self._processed_cache.popitem(last=False)
        self._processed_cache[cache_key] = processed.copy()
        return processed

    def build_preview_image(self, frame: Image.Image, playing: bool) -> Image.Image:
        mask = frame.convert("L").point(lambda p: 255 if p == 0 else 0, mode="L")
        preview = Image.new("RGB", (WIDTH, HEIGHT), PREVIEW_BG)
        preview.paste(PREVIEW_FG, mask=mask)
        preview = preview.resize(PREVIEW_SIZE, Image.NEAREST)
        if not playing:
            preview = preview.filter(ImageFilter.BoxBlur(0.2))
        return preview
