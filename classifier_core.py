import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional


class ClassifierCoreError(Exception):
    """Base exception for image classification workflow errors."""


class KeyNotBoundError(ClassifierCoreError):
    pass


class NoCurrentImageError(ClassifierCoreError):
    pass


class SourceFileMissingError(ClassifierCoreError):
    pass


class MoveFailedError(ClassifierCoreError):
    pass


class UndoConflictError(ClassifierCoreError):
    pass


def scan_images(source_folder: Path, supported_formats: Iterable[str]) -> List[Path]:
    normalized_formats = {ext.lower() for ext in supported_formats}
    return sorted(
        path
        for path in Path(source_folder).iterdir()
        if path.is_file() and path.suffix.lower() in normalized_formats
    )


def resolve_target_path(target_dir: Path, filename: str) -> Path:
    target_dir = Path(target_dir)
    original = target_dir / filename
    if not original.exists():
        return original

    stem = original.stem
    suffix = original.suffix
    counter = 1
    while True:
        candidate = target_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _numbered_filename(stem: str, suffix: str, counter: int) -> str:
    if counter == 0:
        return f"{stem}{suffix}"
    return f"{stem}_{counter}{suffix}"


def resolve_pair_target_paths(target_dir: Path, image_filename: str) -> tuple[Path, Path]:
    target_dir = Path(target_dir)
    image_path = Path(image_filename)
    counter = 0
    while True:
        target_stem = image_path.stem
        image_target = target_dir / _numbered_filename(
            target_stem,
            image_path.suffix,
            counter,
        )
        xml_target = target_dir / _numbered_filename(target_stem, ".xml", counter)
        if not image_target.exists() and not xml_target.exists():
            return image_target, xml_target
        counter += 1


@dataclass
class MoveRecord:
    source: Path
    target: Path
    key: str
    category: str
    xml_source: Optional[Path] = None
    xml_target: Optional[Path] = None


@dataclass
class ClassifierSession:
    source_folder: Path
    target_folder: Path
    supported_formats: List[str]
    key_bindings: Dict[str, str]
    images: List[Path] = field(default_factory=list)
    current_index: int = 0
    history: List[MoveRecord] = field(default_factory=list)
    move_xml_pairs: bool = False

    def refresh(self) -> None:
        previous = self.current_image()
        self.images = scan_images(self.source_folder, self.supported_formats)

        if previous in self.images:
            self.current_index = self.images.index(previous)
            return

        if not self.images:
            self.current_index = 0
            return

        self.current_index = min(self.current_index, len(self.images) - 1)

    def current_image(self) -> Optional[Path]:
        if not self.images:
            return None

        if self.current_index < 0:
            self.current_index = 0
        if self.current_index >= len(self.images):
            self.current_index = len(self.images) - 1

        return self.images[self.current_index]

    def classify_current(self, key: str) -> MoveRecord:
        if key not in self.key_bindings:
            raise KeyNotBoundError(f"No category is bound to key: {key}")

        source = self.current_image()
        if source is None:
            raise NoCurrentImageError("No image is selected.")
        if not source.exists():
            raise SourceFileMissingError(f"Source image no longer exists: {source}")

        category = self.key_bindings[key]
        category_dir = Path(self.target_folder) / category
        xml_source = source.with_suffix(".xml") if self.move_xml_pairs else None
        xml_target: Optional[Path] = None

        if xml_source is not None and xml_source.is_file():
            target, xml_target = resolve_pair_target_paths(category_dir, source.name)
        else:
            xml_source = None
            target = resolve_target_path(category_dir, source.name)

        record = MoveRecord(
            source=source,
            target=target,
            key=key,
            category=category,
            xml_source=xml_source,
            xml_target=xml_target,
        )

        image_moved = False
        try:
            category_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            image_moved = True
            if xml_source is not None and xml_target is not None:
                shutil.move(str(xml_source), str(xml_target))
        except Exception as exc:
            rollback_error = None
            if image_moved and target.exists() and not source.exists():
                try:
                    shutil.move(str(target), str(source))
                except Exception as rollback_exc:
                    rollback_error = rollback_exc
            message = f"Failed to move {source} to {target}: {exc}"
            if rollback_error is not None:
                message += f"; rollback failed: {rollback_error}"
            raise MoveFailedError(message) from exc

        if source in self.images:
            removed_index = self.images.index(source)
            self.images.pop(removed_index)
            self.current_index = min(removed_index, max(len(self.images) - 1, 0))
        else:
            self.current_index = min(self.current_index, max(len(self.images) - 1, 0))

        self.history.append(record)
        return record

    def undo_last(self) -> MoveRecord:
        if not self.history:
            raise NoCurrentImageError("No move operation can be undone.")

        record = self.history[-1]
        if record.source.exists():
            raise UndoConflictError(f"Undo would overwrite existing file: {record.source}")
        if record.xml_source is not None and record.xml_source.exists():
            raise UndoConflictError(
                f"Undo would overwrite existing XML file: {record.xml_source}"
            )
        if not record.target.is_file():
            raise SourceFileMissingError(f"Moved file no longer exists: {record.target}")
        if record.xml_target is not None and not record.xml_target.is_file():
            raise SourceFileMissingError(
                f"Moved XML file no longer exists: {record.xml_target}"
            )

        image_restored = False
        try:
            record.source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(record.target), str(record.source))
            image_restored = True
            if record.xml_source is not None and record.xml_target is not None:
                record.xml_source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(record.xml_target), str(record.xml_source))
        except Exception as exc:
            rollback_error = None
            if image_restored and record.source.exists() and not record.target.exists():
                try:
                    shutil.move(str(record.source), str(record.target))
                except Exception as rollback_exc:
                    rollback_error = rollback_exc
            message = f"Failed to undo move {record.target}: {exc}"
            if rollback_error is not None:
                message += f"; rollback failed: {rollback_error}"
            raise MoveFailedError(message) from exc

        insert_at = min(self.current_index, len(self.images))
        self.images.insert(insert_at, record.source)
        self.current_index = insert_at
        self.history.pop()
        return record
