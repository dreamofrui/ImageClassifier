from copy import deepcopy
from typing import Any, Dict, List, Tuple


DEFAULT_PROFILE_NAME = "default"


def normalize_binding_profiles(
    config: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, str]], str, bool, List[str]]:
    """Ensure config has binding profiles and sync the active profile to legacy bindings."""
    migrated = False
    warnings: List[str] = []

    legacy_bindings = _valid_bindings(config.get("default_key_bindings", {}))
    profiles = _valid_profiles(config.get("binding_profiles", {}))

    if not profiles:
        profiles = {
            DEFAULT_PROFILE_NAME: deepcopy(legacy_bindings),
        }
        migrated = True

    if DEFAULT_PROFILE_NAME not in profiles:
        profiles[DEFAULT_PROFILE_NAME] = deepcopy(legacy_bindings)
        migrated = True

    active_profile = config.get("active_binding_profile")
    if active_profile not in profiles:
        if active_profile:
            warnings.append(f"按键方案 '{active_profile}' 不存在，已切换到默认方案")
        active_profile = DEFAULT_PROFILE_NAME
        migrated = True

    config["binding_profiles"] = deepcopy(profiles)
    config["active_binding_profile"] = active_profile
    config["default_key_bindings"] = deepcopy(profiles[active_profile])

    return profiles, active_profile, migrated, warnings


def _valid_profiles(raw_profiles: Any) -> Dict[str, Dict[str, str]]:
    if not isinstance(raw_profiles, dict):
        return {}

    profiles: Dict[str, Dict[str, str]] = {}
    for name, bindings in raw_profiles.items():
        profile_name = str(name).strip()
        if not profile_name:
            continue
        profiles[profile_name] = _valid_bindings(bindings)
    return profiles


def _valid_bindings(raw_bindings: Any) -> Dict[str, str]:
    if not isinstance(raw_bindings, dict):
        return {}

    bindings: Dict[str, str] = {}
    for key, folder in raw_bindings.items():
        key_text = str(key).strip()
        folder_text = str(folder).strip()
        if len(key_text) == 1 and folder_text:
            bindings[key_text] = folder_text
    return bindings
