import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from classifier_core import (
    ClassifierSession,
    KeyNotBoundError,
    MoveFailedError,
    SourceFileMissingError,
    UndoConflictError,
    resolve_target_path,
    scan_images,
)


class ClassifierCoreTest(unittest.TestCase):
    def test_scan_images_returns_supported_files_sorted_non_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.JPG").write_bytes(b"x")
            (root / "a.png").write_bytes(b"x")
            (root / "notes.txt").write_text("skip")
            nested = root / "nested"
            nested.mkdir()
            (nested / "c.jpg").write_bytes(b"x")

            images = scan_images(root, [".jpg", ".png"])

            self.assertEqual([p.name for p in images], ["a.png", "b.JPG"])

    def test_resolve_target_path_appends_counter_when_name_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp)
            (target_dir / "a.jpg").write_bytes(b"existing")

            target_path = resolve_target_path(target_dir, "a.jpg")

            self.assertEqual(target_path, target_dir / "a_1.jpg")

    def test_classify_current_moves_file_and_advances_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "b.jpg").write_bytes(b"b")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.source, source / "a.jpg")
            self.assertEqual(record.target, target / "PT" / "a.jpg")
            self.assertFalse((source / "a.jpg").exists())
            self.assertTrue((target / "PT" / "a.jpg").exists())
            self.assertEqual([p.name for p in session.images], ["b.jpg"])
            self.assertEqual(session.current_image(), source / "b.jpg")

    def test_classify_current_treats_lowercase_and_uppercase_keys_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "lower_pt", "P": "upper_pt"},
            )
            session.refresh()

            record = session.classify_current("P")

            self.assertEqual(record.category, "upper_pt")
            self.assertEqual(record.target, target / "upper_pt" / "a.jpg")
            self.assertTrue((target / "upper_pt" / "a.jpg").exists())
            self.assertFalse((target / "lower_pt").exists())

    def test_classify_current_default_mode_leaves_matching_xml_in_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.source, source / "a.jpg")
            self.assertEqual(record.target, target / "PT" / "a.jpg")
            self.assertIsNone(record.xml_source)
            self.assertIsNone(record.xml_target)
            self.assertTrue((source / "a.xml").exists())
            self.assertFalse((target / "PT" / "a.xml").exists())

    def test_classify_current_xml_pair_mode_moves_matching_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.target, target / "PT" / "a.jpg")
            self.assertEqual(record.xml_source, source / "a.xml")
            self.assertEqual(record.xml_target, target / "PT" / "a.xml")
            self.assertFalse((source / "a.jpg").exists())
            self.assertFalse((source / "a.xml").exists())
            self.assertTrue((target / "PT" / "a.jpg").exists())
            self.assertTrue((target / "PT" / "a.xml").exists())

    def test_classify_current_xml_pair_mode_allows_missing_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.target, target / "PT" / "a.jpg")
            self.assertIsNone(record.xml_source)
            self.assertIsNone(record.xml_target)
            self.assertTrue((target / "PT" / "a.jpg").exists())

    def test_classify_current_xml_pair_mode_keeps_pair_stem_on_image_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            category = target / "PT"
            source.mkdir()
            category.mkdir(parents=True)
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            (category / "a.jpg").write_bytes(b"existing")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.target, category / "a_1.jpg")
            self.assertEqual(record.xml_target, category / "a_1.xml")
            self.assertTrue((category / "a_1.jpg").exists())
            self.assertTrue((category / "a_1.xml").exists())

    def test_classify_current_xml_pair_mode_skips_conflicting_xml_pair_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            category = target / "PT"
            source.mkdir()
            category.mkdir(parents=True)
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            (category / "a.jpg").write_bytes(b"existing image")
            (category / "a_1.xml").write_text("existing xml", encoding="utf-8")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.target, category / "a_2.jpg")
            self.assertEqual(record.xml_target, category / "a_2.xml")
            self.assertTrue((category / "a_2.jpg").exists())
            self.assertTrue((category / "a_2.xml").exists())
            self.assertEqual(
                (category / "a_1.xml").read_text(encoding="utf-8"),
                "existing xml",
            )

    def test_undo_last_restores_latest_move_at_current_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "b.jpg").write_bytes(b"b")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
            )
            session.refresh()
            moved = session.classify_current("p")

            restored = session.undo_last()

            self.assertEqual(restored, moved)
            self.assertTrue((source / "a.jpg").exists())
            self.assertFalse((target / "PT" / "a.jpg").exists())
            self.assertEqual([p.name for p in session.images], ["a.jpg", "b.jpg"])

    def test_undo_last_restores_moved_xml_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            (source / "b.jpg").write_bytes(b"b")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()
            moved = session.classify_current("p")

            restored = session.undo_last()

            self.assertEqual(restored, moved)
            self.assertTrue((source / "a.jpg").exists())
            self.assertTrue((source / "a.xml").exists())
            self.assertFalse((target / "PT" / "a.jpg").exists())
            self.assertFalse((target / "PT" / "a.xml").exists())
            self.assertEqual([p.name for p in session.images], ["a.jpg", "b.jpg"])

    def test_undo_last_rejects_moved_image_target_replaced_by_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "b.jpg").write_bytes(b"b")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
            )
            session.refresh()
            moved = session.classify_current("p")
            history_before = list(session.history)
            images_before = list(session.images)
            current_index_before = session.current_index
            moved.target.unlink()
            moved.target.mkdir()

            with self.assertRaises(SourceFileMissingError):
                session.undo_last()

            self.assertTrue(moved.target.is_dir())
            self.assertFalse(moved.source.exists())
            self.assertEqual(session.history, history_before)
            self.assertEqual(session.images, images_before)
            self.assertEqual(session.current_index, current_index_before)

    def test_undo_last_rejects_moved_xml_target_replaced_by_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            (source / "b.jpg").write_bytes(b"b")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()
            moved = session.classify_current("p")
            history_before = list(session.history)
            images_before = list(session.images)
            current_index_before = session.current_index
            moved.xml_target.unlink()
            moved.xml_target.mkdir()

            with self.assertRaises(SourceFileMissingError):
                session.undo_last()

            self.assertTrue(moved.target.is_file())
            self.assertTrue(moved.xml_target.is_dir())
            self.assertFalse(moved.source.exists())
            self.assertFalse(moved.xml_source.exists())
            self.assertEqual(session.history, history_before)
            self.assertEqual(session.images, images_before)
            self.assertEqual(session.current_index, current_index_before)

    def test_undo_last_rejects_removed_moved_image_target_with_xml_without_state_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()
            session.classify_current("p")
            moved = session.history[-1]
            images_before = list(session.images)
            current_index_before = session.current_index
            moved.target.unlink()

            with self.assertRaises(SourceFileMissingError):
                session.undo_last()

            self.assertFalse(moved.source.exists())
            self.assertFalse(moved.xml_source.exists())
            self.assertTrue(moved.xml_target.is_file())
            self.assertEqual(session.history, [moved])
            self.assertEqual(session.images, images_before)
            self.assertEqual(session.current_index, current_index_before)

    def test_undo_last_rejects_removed_moved_xml_target_without_state_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            (source / "b.jpg").write_bytes(b"b")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()
            moved = session.classify_current("p")
            history_before = list(session.history)
            images_before = list(session.images)
            current_index_before = session.current_index
            moved.xml_target.unlink()

            with self.assertRaises(SourceFileMissingError):
                session.undo_last()

            self.assertTrue(moved.target.is_file())
            self.assertFalse(moved.xml_target.exists())
            self.assertFalse(moved.source.exists())
            self.assertFalse(moved.xml_source.exists())
            self.assertEqual(session.history, history_before)
            self.assertEqual(session.images, images_before)
            self.assertEqual(session.current_index, current_index_before)

    def test_undo_last_rolls_back_image_when_xml_restore_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            (source / "b.jpg").write_bytes(b"b")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()
            moved = session.classify_current("p")
            history_before = list(session.history)
            images_before = list(session.images)
            current_index_before = session.current_index
            original_move = shutil.move
            move_calls = []

            def fail_xml_restore(source_path, target_path):
                move_calls.append((Path(source_path), Path(target_path)))
                if len(move_calls) == 2:
                    raise OSError("xml restore failed")
                return original_move(source_path, target_path)

            with patch("classifier_core.shutil.move", side_effect=fail_xml_restore):
                with self.assertRaises(MoveFailedError):
                    session.undo_last()

            self.assertEqual(len(move_calls), 3)
            self.assertTrue(moved.target.is_file())
            self.assertFalse(moved.source.exists())
            self.assertTrue(moved.xml_target.is_file())
            self.assertFalse(moved.xml_source.exists())
            self.assertNotIn(moved.source, session.images)
            self.assertEqual(session.history, history_before)
            self.assertEqual(session.images, images_before)
            self.assertEqual(session.current_index, current_index_before)

    def test_undo_last_refuses_to_overwrite_existing_source_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()
            moved = session.classify_current("p")
            history_before = list(session.history)
            images_before = list(session.images)
            current_index_before = session.current_index
            (source / "a.xml").write_text("new xml", encoding="utf-8")

            with self.assertRaises(UndoConflictError):
                session.undo_last()

            self.assertTrue(moved.target.exists())
            self.assertTrue(moved.xml_target.exists())
            self.assertEqual(
                (source / "a.xml").read_text(encoding="utf-8"),
                "new xml",
            )
            self.assertEqual(session.history, history_before)
            self.assertEqual(session.images, images_before)
            self.assertEqual(session.current_index, current_index_before)

    def test_unknown_classification_key_does_not_move_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
            )
            session.refresh()

            with self.assertRaises(KeyNotBoundError):
                session.classify_current("x")

            self.assertTrue((source / "a.jpg").exists())
            self.assertFalse(target.exists())

    def test_refresh_keeps_current_file_selected_when_it_still_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            (source / "a.jpg").write_bytes(b"a")
            (source / "b.jpg").write_bytes(b"b")
            session = ClassifierSession(
                source_folder=source,
                target_folder=source.parent,
                supported_formats=[".jpg"],
                key_bindings={},
            )
            session.refresh()
            session.current_index = 1
            (source / "c.jpg").write_bytes(b"c")

            session.refresh()

            self.assertEqual(session.current_image(), source / "b.jpg")

    def test_undo_refuses_to_overwrite_existing_source_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
            )
            session.refresh()
            moved = session.classify_current("p")
            history_before = list(session.history)
            images_before = list(session.images)
            current_index_before = session.current_index
            (source / "a.jpg").write_bytes(b"new")

            with self.assertRaises(UndoConflictError):
                session.undo_last()

            self.assertTrue(moved.target.exists())
            self.assertEqual((source / "a.jpg").read_bytes(), b"new")
            self.assertEqual(session.history, history_before)
            self.assertEqual(session.images, images_before)
            self.assertEqual(session.current_index, current_index_before)

    def test_classify_current_cleans_up_duplicate_when_copy_succeeds_but_unlink_fails(self):
        """Test that duplicate files are cleaned up when shutil.move's unlink fails."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
            )
            session.refresh()

            # Mock shutil.move to simulate copy success + unlink failure
            original_move = shutil.move
            call_count = [0]

            def mock_move(src, dst):
                call_count[0] += 1
                if call_count[0] == 1:  # First call: image move
                    # Simulate copy+unlink where copy succeeds but unlink fails
                    shutil.copy2(src, dst)
                    raise OSError("Simulated unlink failure")
                return original_move(src, dst)

            with patch("classifier_core.shutil.move", side_effect=mock_move):
                with self.assertRaises(MoveFailedError):
                    session.classify_current("p")

            # Verify: source should still exist, target should be cleaned up
            self.assertTrue((source / "a.jpg").exists(), "Source file should still exist")
            self.assertFalse(
                (target / "PT" / "a.jpg").exists(),
                "Duplicate target file should be cleaned up",
            )
            self.assertEqual(len(session.history), 0, "History should be empty after failed move")

    def test_undo_last_cleans_up_duplicate_when_copy_succeeds_but_unlink_fails(self):
        """Test that duplicate files are cleaned up during undo when unlink fails."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
            )
            session.refresh()
            moved = session.classify_current("p")

            # Mock shutil.move for undo operation
            original_move = shutil.move
            call_count = [0]

            def mock_move(src, dst):
                call_count[0] += 1
                if call_count[0] == 1:  # First call during undo: restore image
                    # Simulate copy+unlink where copy succeeds but unlink fails
                    shutil.copy2(src, dst)
                    raise OSError("Simulated unlink failure during undo")
                return original_move(src, dst)

            with patch("classifier_core.shutil.move", side_effect=mock_move):
                with self.assertRaises(MoveFailedError):
                    session.undo_last()

            # Verify: target should still exist, duplicate source should be cleaned up
            self.assertTrue(
                (target / "PT" / "a.jpg").exists(),
                "Target file should still exist after failed undo",
            )
            self.assertFalse(
                (source / "a.jpg").exists(),
                "Duplicate source file should be cleaned up",
            )
            self.assertEqual(
                len(session.history), 1, "History should still contain the original move"
            )


if __name__ == "__main__":
    unittest.main()
