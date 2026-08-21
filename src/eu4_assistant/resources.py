from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GameResourceResolver:
    """Resolve EU4 resources from one optional mod overlay and vanilla fallback."""

    game_dir: Path
    mod_dir: Path | None = None

    @classmethod
    def create(
        cls, game_dir: str | Path, mod_dir: str | Path | None = None
    ) -> "GameResourceResolver":
        mod_root = Path(mod_dir).resolve() if mod_dir else None
        return cls(Path(game_dir).resolve(), mod_root)

    def resolve_file(self, relative: str | Path) -> Path:
        relative_path = Path(relative)
        if self.mod_dir is not None:
            candidate = self.mod_dir / relative_path
            if candidate.is_file():
                return candidate
        return self.game_dir / relative_path

    def overlay_files(self, relative_dir: str | Path, pattern: str) -> list[Path]:
        """Merge a resource directory, with equal relative paths won by the mod."""
        relative_path = Path(relative_dir)
        layers: list[dict[str, Path]] = []
        for root in (self.game_dir, self.mod_dir):
            files: dict[str, Path] = {}
            if root is None:
                layers.append(files)
                continue
            directory = root / relative_path
            if directory.is_dir():
                for path in directory.glob(pattern):
                    if path.is_file():
                        key = path.relative_to(directory).as_posix().lower()
                        files[key] = path
            layers.append(files)
        vanilla, mod = layers
        vanilla_only = [vanilla[key] for key in sorted(vanilla) if key not in mod]
        return vanilla_only + [mod[key] for key in sorted(mod)]

    def is_valid_mod_root(self) -> bool:
        if self.mod_dir is None or not self.mod_dir.is_dir():
            return False
        return any((self.mod_dir / name).is_dir() for name in ("map", "common", "gfx"))
