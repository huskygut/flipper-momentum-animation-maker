import shutil
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from src.core.bm_encoder import BMEncoder


@dataclass
class ExportResult:
    pack_dir: Path
    anim_dir: Path
    zip_path: Path | None
    frame_count: int
    manifest_count: int


class PackExporter:
    def __init__(self, image_processor, manifest_builder):
        self.image_processor = image_processor
        self.manifest_builder = manifest_builder

    def _cleanup_empty_pack_dirs(self, pack_dir: Path, anims_dir: Path, out_root_path: Path) -> None:
        try:
            if anims_dir.exists() and not any(anims_dir.iterdir()):
                anims_dir.rmdir()
            if pack_dir.exists() and pack_dir.parent == out_root_path and not any(pack_dir.iterdir()):
                pack_dir.rmdir()
        except Exception:
            pass

    def export_pack(
        self,
        frames: Iterable[Image.Image],
        out_root: str,
        pack_name: str,
        anim_base: str,
        create_zip: bool,
    ) -> ExportResult:

        out_root_path = Path(out_root)
        if not out_root_path.exists() or not out_root_path.is_dir():
            raise ValueError("Export folder does not exist or is not a directory.")

        pack_dir = out_root_path / pack_name
        anims_dir = pack_dir / "Anims"
        anim_dir_name = f"{anim_base}_128x64"
        anim_dir = anims_dir / anim_dir_name
        zip_path = out_root_path / f"{pack_name}.zip" if create_zip else None

        anims_dir.mkdir(parents=True, exist_ok=True)
        existing_manifest = ""
        manifest_path = anims_dir / "manifest.txt"
        if manifest_path.exists():
            existing_manifest = manifest_path.read_text(encoding="utf-8", errors="ignore")

        frames = list(frames)
        frame_count = len(frames)
        if frame_count <= 0:
            raise ValueError("No frames were provided for export.")

        manifest_content, manifest_count = self.manifest_builder.build_manifest_content(
            existing_manifest, anim_dir_name
        )
        meta_content = self.manifest_builder.build_meta(frame_count)

        temp_root = Path(tempfile.mkdtemp(prefix="flipper_pack_"))
        backup_root = temp_root / "backups"
        backup_root.mkdir(parents=True, exist_ok=True)

        anim_backup = None
        manifest_backup = None
        zip_backup = None

        try:
            temp_anim_dir = temp_root / anim_dir_name
            temp_anim_dir.mkdir(parents=True, exist_ok=True)

            for idx, source_frame in enumerate(frames):
                processed_frame = self.image_processor.process_frame(source_frame)
                (temp_anim_dir / f"frame_{idx}.bm").write_bytes(BMEncoder.convert_bm(processed_frame))
            (temp_anim_dir / "meta.txt").write_text(meta_content, encoding="utf-8", newline="\n")

            temp_manifest_path = temp_root / "manifest.txt"
            temp_manifest_path.write_text(manifest_content, encoding="utf-8", newline="\n")

            if anim_dir.exists():
                anim_backup = backup_root / anim_dir.name
                shutil.move(str(anim_dir), str(anim_backup))
            shutil.move(str(temp_anim_dir), str(anim_dir))

            if manifest_path.exists():
                manifest_backup = backup_root / manifest_path.name
                shutil.copy2(manifest_path, manifest_backup)
            shutil.copy2(temp_manifest_path, manifest_path)

            if zip_path:
                temp_zip_path = temp_root / f"{pack_name}.zip"
                with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for path in pack_dir.rglob("*"):
                        if path.is_file():
                            zf.write(path, path.relative_to(out_root_path))
                if zip_path.exists():
                    zip_backup = backup_root / zip_path.name
                    shutil.move(str(zip_path), str(zip_backup))
                shutil.move(str(temp_zip_path), str(zip_path))

            if anim_backup and anim_backup.exists():
                shutil.rmtree(anim_backup, ignore_errors=True)
            if manifest_backup and manifest_backup.exists():
                manifest_backup.unlink(missing_ok=True)
            if zip_backup and zip_backup.exists():
                zip_backup.unlink(missing_ok=True)

            return ExportResult(
                pack_dir=pack_dir,
                anim_dir=anim_dir,
                zip_path=zip_path,
                frame_count=frame_count,
                manifest_count=manifest_count,
            )
        except Exception:
            if anim_dir.exists():
                shutil.rmtree(anim_dir, ignore_errors=True)
            if anim_backup and anim_backup.exists():
                shutil.move(str(anim_backup), str(anim_dir))
            if manifest_backup and manifest_backup.exists():
                shutil.copy2(manifest_backup, manifest_path)
            elif manifest_path.exists() and not existing_manifest:
                manifest_path.unlink(missing_ok=True)
            if zip_backup and zip_backup.exists():
                if zip_path and zip_path.exists():
                    zip_path.unlink(missing_ok=True)
                shutil.move(str(zip_backup), str(zip_path))
            self._cleanup_empty_pack_dirs(pack_dir, anims_dir, out_root_path)
            raise
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)
