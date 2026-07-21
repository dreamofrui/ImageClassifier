import json
import os
import sys
from pathlib import Path
from typing import Dict, Any


def get_app_dir() -> Path:
    """获取应用程序所在目录（兼容开发模式和打包模式）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的 exe 模式
        return Path(sys.executable).parent
    else:
        # 开发模式
        return Path(__file__).parent


class ConfigManager:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = get_app_dir() / "config.json"
        self.config_path = Path(config_path)
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, default)
            else:
                return default
        return value
    
    def set(self, key: str, value: Any) -> None:
        keys = key.split('.')
        config = self.config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
    
    def save(self) -> None:
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)

    def get_image_classifier_config(self) -> Dict[str, Any]:
        return self.get('image_classifier', {})
