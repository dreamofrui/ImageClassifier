from pathlib import Path
import unittest


class PackagingTest(unittest.TestCase):
    def test_build_script_packages_persistent_config_and_user_guide(self):
        script = Path("build.bat").read_text(encoding="utf-8")

        self.assertIn('copy /Y "..\\config.json" "ImageClassifier_Release\\"', script)
        self.assertIn('copy /Y "..\\USER_GUIDE.md" "ImageClassifier_Release\\"', script)
        self.assertIn("- config.json", script)
        self.assertIn("- USER_GUIDE.md", script)

    def test_build_script_fails_when_release_steps_fail(self):
        script = Path("build.bat").read_text(encoding="utf-8")

        self.assertIn('if errorlevel 1 goto :build_failed', script)
        self.assertIn(':build_failed', script)
        self.assertIn('exit /b 1', script)

    def test_user_guide_source_exists_for_release_packaging(self):
        guide = Path("USER_GUIDE.md")

        self.assertTrue(guide.exists())
        self.assertIn("config.json", guide.read_text(encoding="utf-8"))

    def test_pyinstaller_spec_launches_qt_workbench(self):
        spec = Path("ImageClassifier.spec").read_text(encoding="utf-8")

        self.assertIn("['qt_main.py']", spec)


if __name__ == "__main__":
    unittest.main()
