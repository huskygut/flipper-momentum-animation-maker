from __future__ import annotations

import argparse
import html
import tempfile
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from exporter import PackExporter
from image_processing import ImageProcessor
from manifest import ManifestBuilder
from utils import sanitize_name

MAX_UPLOAD_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class WebExportSettings:
    pack_name: str
    animation_name: str
    fit_mode: str
    threshold: int
    contrast: float
    brightness: float
    sharpen: float
    frame_rate: int
    duration: int
    passive_frames: int
    active_cycles: int
    active_cooldown: int
    hold_last_frame: int
    min_butthurt: int
    max_butthurt: int
    min_level: int
    max_level: int
    weight: int
    target_frames: int
    trim_start: int
    trim_end: int


def _first(fields: dict[str, list[str]], name: str, default: str) -> str:
    values = fields.get(name)
    if not values:
        return default
    return values[0]


def _int_field(
    fields: dict[str, list[str]],
    name: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        value = int(_first(fields, name, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _float_field(
    fields: dict[str, list[str]],
    name: str,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        value = float(_first(fields, name, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _build_settings(fields: dict[str, list[str]]) -> WebExportSettings:
    fit_mode = _first(fields, "fit_mode", "contain")
    if fit_mode not in {"contain", "cover"}:
        fit_mode = "contain"

    return WebExportSettings(
        pack_name=sanitize_name(_first(fields, "pack_name", "MomentumPack"), "MomentumPack"),
        animation_name=sanitize_name(_first(fields, "animation_name", "animation"), "animation"),
        fit_mode=fit_mode,
        threshold=_int_field(fields, "threshold", 128, 0, 255),
        contrast=_float_field(fields, "contrast", 1.0, 0.1, 5.0),
        brightness=_float_field(fields, "brightness", 1.0, 0.1, 5.0),
        sharpen=_float_field(fields, "sharpen", 0.0, 0.0, 5.0),
        frame_rate=_int_field(fields, "frame_rate", 5, 1, 60),
        duration=_int_field(fields, "duration", 360, 1, 100000),
        passive_frames=_int_field(fields, "passive_frames", 1, 1, 100000),
        active_cycles=_int_field(fields, "active_cycles", 1, 1, 100000),
        active_cooldown=_int_field(fields, "active_cooldown", 1, 0, 100000),
        hold_last_frame=_int_field(fields, "hold_last_frame", 0, 0, 100000),
        min_butthurt=_int_field(fields, "min_butthurt", 0, 0, 18),
        max_butthurt=_int_field(fields, "max_butthurt", 18, 0, 18),
        min_level=_int_field(fields, "min_level", 1, 0, 30),
        max_level=_int_field(fields, "max_level", 30, 0, 30),
        weight=_int_field(fields, "weight", 3, 1, 100000),
        target_frames=_int_field(fields, "target_frames", 0, 0, 100000),
        trim_start=_int_field(fields, "trim_start", 0, 0, 100000),
        trim_end=_int_field(fields, "trim_end", 0, 0, 100000),
    )


def _select_frames(frames, settings: WebExportSettings):
    start = min(settings.trim_start, len(frames))
    end = len(frames) - min(settings.trim_end, len(frames) - start)
    selected = frames[start:end]
    if not selected:
        raise ValueError("Trim settings removed every frame. Keep at least one frame.")

    target = settings.target_frames
    if target and target < len(selected):
        if target == 1:
            selected = [selected[0]]
        else:
            step = (len(selected) - 1) / (target - 1)
            selected = [selected[round(i * step)] for i in range(target)]
    return selected


def _parse_multipart(content_type: str, body: bytes) -> tuple[dict[str, list[str]], bytes, str]:
    header_blob = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
    message = BytesParser(policy=default).parsebytes(header_blob + body)
    fields: dict[str, list[str]] = {}
    upload_bytes = b""
    upload_name = "upload.gif"

    if not message.is_multipart():
        raise ValueError("Expected a multipart form upload.")

    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        if disposition != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            upload_bytes = payload
            upload_name = filename
        elif name:
            fields.setdefault(name, []).append(payload.decode("utf-8", errors="replace"))

    return fields, upload_bytes, upload_name


def _make_export_zip(fields: dict[str, list[str]], upload_bytes: bytes, upload_name: str) -> tuple[str, bytes]:
    if not upload_bytes:
        raise ValueError("Choose a GIF file before exporting.")
    if not upload_name.lower().endswith(".gif"):
        raise ValueError("Only GIF uploads are supported.")

    settings = _build_settings(fields)
    image_processor = ImageProcessor(
        fit_mode_getter=lambda: settings.fit_mode,
        threshold_getter=lambda: settings.threshold,
        contrast_getter=lambda: settings.contrast,
        brightness_getter=lambda: settings.brightness,
        sharpen_getter=lambda: settings.sharpen,
    )
    manifest_builder = ManifestBuilder(
        frame_rate_getter=lambda: settings.frame_rate,
        duration_getter=lambda: settings.duration,
        passive_frames_getter=lambda: settings.passive_frames,
        active_cycles_getter=lambda: settings.active_cycles,
        active_cooldown_getter=lambda: settings.active_cooldown,
        min_butthurt_getter=lambda: settings.min_butthurt,
        max_butthurt_getter=lambda: settings.max_butthurt,
        min_level_getter=lambda: settings.min_level,
        max_level_getter=lambda: settings.max_level,
        weight_getter=lambda: settings.weight,
        hold_last_frame_getter=lambda: settings.hold_last_frame,
    )
    exporter = PackExporter(image_processor, manifest_builder)

    with tempfile.TemporaryDirectory(prefix="fmam_web_") as temp_dir:
        temp_path = Path(temp_dir)
        upload_path = temp_path / "upload.gif"
        upload_path.write_bytes(upload_bytes)
        frames = image_processor.load_gif_frames(str(upload_path))
        selected_frames = _select_frames(frames, settings)
        exporter.export_pack(selected_frames, str(temp_path), settings.pack_name, settings.animation_name, create_zip=True)
        return f"{settings.pack_name}.zip", (temp_path / f"{settings.pack_name}.zip").read_bytes()


class AnimationMakerHandler(BaseHTTPRequestHandler):
    server_version = "FMAMWeb/1.0"

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_bytes(b"ok", "text/plain")
            return
        self._send_html(INDEX_HTML)

    def do_POST(self) -> None:
        if self.path != "/convert":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > MAX_UPLOAD_BYTES:
                raise ValueError("Upload is too large. Use a GIF smaller than 64 MB.")
            content_type = self.headers.get("Content-Type", "")
            body = self.rfile.read(content_length)
            fields, upload_bytes, upload_name = _parse_multipart(content_type, body)
            filename, zip_bytes = _make_export_zip(fields, upload_bytes, upload_name)
        except Exception as exc:
            self._send_html(INDEX_HTML.replace("{{ERROR}}", html.escape(str(exc))), HTTPStatus.BAD_REQUEST)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(zip_bytes)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(zip_bytes)

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _send_html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes(content.replace("{{ERROR}}", "").encode(), "text/html; charset=utf-8", status)

    def _send_bytes(self, content: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Flipper Momentum Animation Maker Web</title>
  <style>
    :root { color-scheme: dark; --bg:#0f0f10; --panel:#18181b; --fg:#f3f3f3; --muted:#b8b8c2; --accent:#ff8c1a; --border:#38383f; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: radial-gradient(circle at top, #2b2118, var(--bg) 42rem); color:var(--fg); }
    main { max-width: 1120px; margin: 0 auto; padding: 32px 18px 56px; }
    h1 { margin:0; font-size: clamp(2rem, 5vw, 4.2rem); line-height: .95; }
    p { color: var(--muted); font-size: 1.05rem; max-width: 780px; }
    form { background: rgba(24,24,27,.92); border:1px solid var(--border); border-radius: 24px; padding: 22px; box-shadow: 0 24px 70px rgba(0,0,0,.35); }
    fieldset { border:1px solid var(--border); border-radius: 18px; padding: 18px; margin: 0 0 18px; background: rgba(32,32,36,.55); }
    legend { padding: 0 8px; color: var(--accent); font-weight: 800; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
    label { display:grid; gap: 6px; font-weight: 650; }
    input, select { width:100%; border:1px solid var(--border); border-radius: 12px; padding: 11px 12px; background:#111214; color:var(--fg); }
    input[type="file"] { padding: 18px; border-style: dashed; background:#151515; }
    button { width:100%; border:0; border-radius: 16px; padding: 16px 18px; background: linear-gradient(135deg, var(--accent), #ffb35f); color:#17100b; font-size:1.1rem; font-weight:900; cursor:pointer; }
    .messages:not(:empty) { margin:0 0 18px; padding: 14px 16px; border-radius: 14px; background:#331d1d; border:1px solid #7a3434; }
    .hint { font-size:.9rem; color:var(--muted); font-weight: 500; }
  </style>
</head>
<body>
<main>
  <h1>Flipper Momentum Animation Maker</h1>
  <p>Upload a GIF, tune conversion settings, and download a Momentum-compatible animation pack ZIP with .bm frames, meta.txt, and manifest.txt.</p>
  <div class="messages">{{ERROR}}</div>
  <form method="post" action="/convert" enctype="multipart/form-data">
    <fieldset>
      <legend>Upload</legend>
      <div class="grid">
        <label>GIF file<input required type="file" name="gif_file" accept="image/gif"></label>
        <label>Pack name<input name="pack_name" value="MomentumPack"></label>
        <label>Animation name<input name="animation_name" value="animation"></label>
        <label>Fit mode<select name="fit_mode"><option value="contain">Contain</option><option value="cover">Cover</option></select></label>
      </div>
    </fieldset>
    <fieldset>
      <legend>Image conversion</legend>
      <div class="grid">
        <label>Threshold<input type="number" name="threshold" value="128" min="0" max="255"></label>
        <label>Contrast<input type="number" name="contrast" value="1.0" min="0.1" max="5" step="0.1"></label>
        <label>Brightness<input type="number" name="brightness" value="1.0" min="0.1" max="5" step="0.1"></label>
        <label>Sharpen<input type="number" name="sharpen" value="0.0" min="0" max="5" step="0.1"></label>
      </div>
    </fieldset>
    <fieldset>
      <legend>Frame tools</legend>
      <div class="grid">
        <label>Target frames <span class="hint">0 keeps all frames</span><input type="number" name="target_frames" value="0" min="0"></label>
        <label>Trim start<input type="number" name="trim_start" value="0" min="0"></label>
        <label>Trim end<input type="number" name="trim_end" value="0" min="0"></label>
        <label>Hold last frame<input type="number" name="hold_last_frame" value="0" min="0"></label>
      </div>
    </fieldset>
    <fieldset>
      <legend>Momentum metadata</legend>
      <div class="grid">
        <label>Frame rate<input type="number" name="frame_rate" value="5" min="1" max="60"></label>
        <label>Duration<input type="number" name="duration" value="360" min="1"></label>
        <label>Passive frames<input type="number" name="passive_frames" value="1" min="1"></label>
        <label>Active cycles<input type="number" name="active_cycles" value="1" min="1"></label>
        <label>Active cooldown<input type="number" name="active_cooldown" value="1" min="0"></label>
        <label>Min butthurt<input type="number" name="min_butthurt" value="0" min="0" max="18"></label>
        <label>Max butthurt<input type="number" name="max_butthurt" value="18" min="0" max="18"></label>
        <label>Min level<input type="number" name="min_level" value="1" min="0" max="30"></label>
        <label>Max level<input type="number" name="max_level" value="30" min="0" max="30"></label>
        <label>Weight<input type="number" name="weight" value="3" min="1"></label>
      </div>
    </fieldset>
    <button type="submit">Export Momentum ZIP</button>
  </form>
</main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Flipper Momentum Animation Maker web app.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AnimationMakerHandler)
    print(f"Serving on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
