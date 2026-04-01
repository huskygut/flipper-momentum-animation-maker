from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageEnhance, ImageSequence, ImageDraw

from constants import (
    PREVIEW_BEZEL,
    PREVIEW_BG,
    PREVIEW_FG,
    PREVIEW_FRAME,
    PREVIEW_GRID,
    PREVIEW_SCALE,
    PREVIEW_SIZE,
    PREVIEW_OUTER_PAD,
    PREVIEW_BEZEL_PAD,
    WIDTH,
    HEIGHT,
)
from utils import sanitize_name

_CACHE_MAX = 256  # Maximum processed frames to keep in memory


class ImageProcessor:
    def __init__(self, fit_mode_getter, threshold_getter, contrast_getter, brightness_getter, sharpen_getter):
        self.fit_mode_getter = fit_mode_getter
        self.threshold_getter = threshold_getter
        self.contrast_getter = contrast_getter
        self.brightness_getter = brightness_getter
        self.sharpen_getter = sharpen_getter
        # OrderedDict used as a simple LRU: recently used entries are moved
        # to the end; the oldest entry is evicted one-at-a-time when the limit
        # is reached — avoiding the "clear everything at once" stall of the
        # previous dict implementation.
        # Key: (id(img), threshold, WIDTH, contrast, brightness, sharpen, fit_mode).
        # id(img) is safe here because all source frames live in all_frames
        # for the full lifetime of the loaded GIF, preventing address reuse.
        self._processed_cache: OrderedDict[tuple, Image.Image] = OrderedDict()

    def clear_cache(self) -> None:
        for cached in self._processed_cache.values():
            try:
                cached.close()
            except Exception:
                pass
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

            if self.fit_mode_getter() == "cover":
                scale = max(WIDTH / src.width, HEIGHT / src.height)
            else:
                scale = min(WIDTH / src.width, HEIGHT / src.height)

            new_size = (
                max(1, int(round(src.width * scale))),
                max(1, int(round(src.height * scale))),
            )
            with Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 255)) as bg:
                with src.resize(new_size, Image.LANCZOS) as resized:
                    x = (WIDTH - resized.width) // 2
                    y = (HEIGHT - resized.height) // 2
                    bg.paste(resized, (x, y), resized)
                fitted = bg.convert("RGB")
        return fitted

    def process_frame(self, img: Image.Image) -> Image.Image:
        cache_key = (
            id(img),
            max(0, min(255, int(self.threshold_getter()))),
            WIDTH,
            round(max(0.1, float(self.contrast_getter())), 2),
            round(max(0.1, float(self.brightness_getter())), 2),
            round(max(0.0, float(self.sharpen_getter())), 2),
            str(self.fit_mode_getter()),
        )

        if cache_key in self._processed_cache:
            self._processed_cache.move_to_end(cache_key)
            return self._processed_cache[cache_key].copy()

        contrast = max(0.1, float(self.contrast_getter()))
        brightness = max(0.1, float(self.brightness_getter()))
        threshold = max(0, min(255, int(self.threshold_getter())))
        sharpen = max(0.0, float(self.sharpen_getter()))

        with self.fit_image(img) as fitted:
            with fitted.convert("L") as gray:
                with ImageEnhance.Brightness(gray).enhance(brightness) as brightened:
                    with ImageEnhance.Contrast(brightened).enhance(contrast) as contrasted:
                        if sharpen > 0:
                            with ImageEnhance.Sharpness(contrasted).enhance(1.0 + sharpen) as sharpened:
                                processed = sharpened.point(lambda p: 255 if p > threshold else 0, mode="1")
                        else:
                            processed = contrasted.point(lambda p: 255 if p > threshold else 0, mode="1")

        if len(self._processed_cache) >= _CACHE_MAX:
            _, oldest_image = self._processed_cache.popitem(last=False)
            oldest_image.close()
        self._processed_cache[cache_key] = processed
        return processed.copy()

    def build_preview_image(self, frame: Image.Image, mode: str = "accurate") -> Image.Image:
        with frame.convert("L") as gray_frame:
            with gray_frame.point(lambda p: 255 if p == 0 else 0, mode="L") as mask:
                with Image.new("RGB", (WIDTH, HEIGHT), PREVIEW_BG) as screen:
                    screen.paste(PREVIEW_FG, mask=mask)

                    if mode == "soft":
                        return screen.resize(PREVIEW_SIZE, Image.NEAREST)

                    with screen.resize(PREVIEW_SIZE, Image.NEAREST) as scaled_screen:
                        draw = ImageDraw.Draw(scaled_screen)

                        for x in range(PREVIEW_SCALE - 1, PREVIEW_SIZE[0], PREVIEW_SCALE):
                            draw.line((x, 0, x, PREVIEW_SIZE[1] - 1), fill=PREVIEW_GRID)
                        for y in range(PREVIEW_SCALE - 1, PREVIEW_SIZE[1], PREVIEW_SCALE):
                            draw.line((0, y, PREVIEW_SIZE[0] - 1, y), fill=PREVIEW_GRID)

                        preview = Image.new("RGB", (PREVIEW_SIZE[0] + PREVIEW_OUTER_PAD * 2, PREVIEW_SIZE[1] + PREVIEW_OUTER_PAD * 2), PREVIEW_FRAME)
                        bezel_rect = (
                            PREVIEW_OUTER_PAD - PREVIEW_BEZEL_PAD,
                            PREVIEW_OUTER_PAD - PREVIEW_BEZEL_PAD,
                            PREVIEW_OUTER_PAD + PREVIEW_SIZE[0] + PREVIEW_BEZEL_PAD - 1,
                            PREVIEW_OUTER_PAD + PREVIEW_SIZE[1] + PREVIEW_BEZEL_PAD - 1,
                        )
                        outer_draw = ImageDraw.Draw(preview)
                        outer_draw.rounded_rectangle(bezel_rect, radius=18, fill=PREVIEW_BEZEL)
                        preview.paste(scaled_screen, (PREVIEW_OUTER_PAD, PREVIEW_OUTER_PAD))
                        outer_draw.rounded_rectangle(bezel_rect, radius=18, outline=PREVIEW_FRAME, width=3)
                        outer_draw.rectangle(
                            (
                                PREVIEW_OUTER_PAD,
                                PREVIEW_OUTER_PAD,
                                PREVIEW_OUTER_PAD + PREVIEW_SIZE[0] - 1,
                                PREVIEW_OUTER_PAD + PREVIEW_SIZE[1] - 1,
                            ),
                            outline=PREVIEW_FRAME,
                        )
                        return preview
