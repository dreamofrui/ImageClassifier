import unittest

from binding_profiles import normalize_binding_profiles


class BindingProfilesTest(unittest.TestCase):
    def test_creates_default_profile_from_legacy_bindings(self):
        config = {
            "default_key_bindings": {
                "p": "PT",
                "q": "QK",
            }
        }

        profiles, active_profile, migrated, warnings = normalize_binding_profiles(config)

        self.assertTrue(migrated)
        self.assertEqual(warnings, [])
        self.assertEqual(active_profile, "default")
        self.assertEqual(profiles, {"default": {"p": "PT", "q": "QK"}})
        self.assertEqual(config["binding_profiles"], profiles)
        self.assertEqual(config["active_binding_profile"], "default")
        self.assertEqual(config["default_key_bindings"], {"p": "PT", "q": "QK"})

    def test_existing_active_profile_syncs_legacy_default_bindings(self):
        config = {
            "default_key_bindings": {
                "x": "old",
            },
            "binding_profiles": {
                "default": {
                    "p": "PT",
                },
                "review": {
                    "1": "accept",
                    "2": "reject",
                },
            },
            "active_binding_profile": "review",
        }

        profiles, active_profile, migrated, warnings = normalize_binding_profiles(config)

        self.assertFalse(migrated)
        self.assertEqual(warnings, [])
        self.assertEqual(active_profile, "review")
        self.assertEqual(profiles["review"], {"1": "accept", "2": "reject"})
        self.assertEqual(config["default_key_bindings"], {"1": "accept", "2": "reject"})


if __name__ == "__main__":
    unittest.main()
