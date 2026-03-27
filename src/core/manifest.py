from pathlib import Path

from src.core.constants import HEIGHT, WIDTH


class ManifestBuilder:
    def __init__(
        self,
        frame_rate_getter,
        duration_getter,
        passive_frames_getter,
        active_cycles_getter,
        active_cooldown_getter,
        min_butthurt_getter,
        max_butthurt_getter,
        min_level_getter,
        max_level_getter,
        weight_getter,
    ):
        self.frame_rate_getter = frame_rate_getter
        self.duration_getter = duration_getter
        self.passive_frames_getter = passive_frames_getter
        self.active_cycles_getter = active_cycles_getter
        self.active_cooldown_getter = active_cooldown_getter
        self.min_butthurt_getter = min_butthurt_getter
        self.max_butthurt_getter = max_butthurt_getter
        self.min_level_getter = min_level_getter
        self.max_level_getter = max_level_getter
        self.weight_getter = weight_getter

    def build_meta(self, frame_count: int) -> str:
        if frame_count <= 0:
            raise ValueError("At least one frame is required to build meta.txt")

        passive = max(1, min(int(self.passive_frames_getter()), frame_count))
        active = max(0, frame_count - passive)
        frame_order = " ".join(str(i) for i in range(frame_count))
        return (
            "Filetype: Flipper Animation\n"
            "Version: 1\n\n"
            f"Width: {WIDTH}\n"
            f"Height: {HEIGHT}\n"
            f"Passive frames: {passive}\n"
            f"Active frames: {active}\n"
            f"Frames order: {frame_order}\n"
            f"Active cycles: {max(1, int(self.active_cycles_getter()))}\n"
            f"Frame rate: {max(1, int(self.frame_rate_getter()))}\n"
            f"Duration: {max(1, int(self.duration_getter()))}\n"
            f"Active cooldown: {max(0, int(self.active_cooldown_getter()))}\n\n"
            "Bubble slots: 0\n"
        )

    def build_manifest_block(self, anim_dir_name: str) -> str:
        min_butthurt = max(0, min(18, int(self.min_butthurt_getter())))
        max_butthurt = max(min_butthurt, min(18, int(self.max_butthurt_getter())))
        min_level = max(0, min(30, int(self.min_level_getter())))
        max_level = max(min_level, min(30, int(self.max_level_getter())))
        weight = max(1, int(self.weight_getter()))
        return (
            f"Name: {anim_dir_name}\n"
            f"Min butthurt: {min_butthurt}\n"
            f"Max butthurt: {max_butthurt}\n"
            f"Min level: {min_level}\n"
            f"Max level: {max_level}\n"
            f"Weight: {weight}\n"
        )

    def _parse_manifest_blocks(self, raw: str) -> dict[str, str]:
        blocks: dict[str, str] = {}
        current_lines: list[str] = []

        def commit() -> None:
            nonlocal current_lines
            if not current_lines:
                return
            name = None
            for line in current_lines:
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip()
                    break
            if name:
                blocks[name] = "\n".join(current_lines).rstrip() + "\n"
            current_lines = []

        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                commit()
                continue
            if stripped.startswith("Filetype:") or stripped.startswith("Version:"):
                continue
            current_lines.append(stripped)
        commit()
        return blocks

    def build_manifest_content(self, existing_raw: str, anim_dir_name: str) -> tuple[str, int]:
        header = "Filetype: Flipper Animation Manifest\nVersion: 1\n\n"
        blocks = self._parse_manifest_blocks(existing_raw)
        blocks[anim_dir_name] = self.build_manifest_block(anim_dir_name)
        ordered_names = sorted(blocks.keys(), key=str.lower)
        content = header + "\n".join(blocks[name].rstrip() + "\n" for name in ordered_names)
        return content.rstrip() + "\n", len(ordered_names)

    def update_manifest(self, anims_dir: Path, anim_dir_name: str) -> int:
        manifest_path = anims_dir / "manifest.txt"
        existing_raw = ""
        if manifest_path.exists():
            existing_raw = manifest_path.read_text(encoding="utf-8", errors="ignore")
        content, count = self.build_manifest_content(existing_raw, anim_dir_name)
        manifest_path.write_text(content, encoding="utf-8", newline="\n")
        return count
