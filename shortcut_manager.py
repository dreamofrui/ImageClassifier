"""
快捷键管理器 - 统一管理所有快捷键配置和绑定
"""
from typing import Dict, List, Callable, Any
import tkinter as tk


class ShortcutManager:
    """快捷键管理器"""

    # 功能定义：动作名称 -> 显示名称
    ACTION_DEFINITIONS = {
        'next': '下一张',
        'previous': '上一张',
        'skip': '跳过',
        'undo': '撤销',
        'refresh': '刷新文件列表',
        'open_folder': '打开文件夹',
        'exit': '退出分类模式',
    }

    # 默认快捷键配置
    DEFAULT_SHORTCUTS = {
        'next': ['d', 'Right', 'Down'],
        'previous': ['a', 'Left', 'Up'],
        'skip': ['s'],
        'undo': ['u'],
        'refresh': ['F5'],
        'open_folder': ['Control-o'],
        'exit': ['Escape'],
    }

    # 按键显示格式化映射
    KEY_DISPLAY_MAP = {
        'Up': '↑',
        'Down': '↓',
        'Left': '←',
        'Right': '→',
        'Escape': 'Esc',
    }

    def __init__(self):
        self.shortcuts: Dict[str, Dict[str, List[str]]] = {}

    def load_from_config(self, shortcuts_config: Dict[str, Any]) -> tuple:
        """
        从配置加载快捷键，自动迁移旧格式

        Args:
            shortcuts_config: shortcuts 配置字典

        Returns:
            (是否发生了迁移, 警告列表)
        """
        # 处理空配置
        if not shortcuts_config:
            shortcuts_config = {}

        # 迁移旧格式
        migrated = self._migrate_old_format(shortcuts_config)

        # 补充缺失的默认配置
        filled = self._fill_missing_defaults(shortcuts_config)
        if filled:
            migrated = True

        # 保存配置
        self.shortcuts = shortcuts_config

        # 校验并返回警告
        warnings = self.validate()

        return migrated, warnings

    def _migrate_old_format(self, shortcuts_config: Dict[str, Any]) -> bool:
        """检测并迁移旧格式，返回是否发生了迁移"""
        migrated = False
        for key, value in shortcuts_config.items():
            if isinstance(value, str):
                # 旧格式: "skip": "s" → 新格式: "skip": {"keys": ["s"]}
                shortcuts_config[key] = {"keys": [value]}
                migrated = True
        return migrated

    def _fill_missing_defaults(self, shortcuts_config: Dict[str, Any]) -> bool:
        """补充缺失的默认配置，返回是否发生了补充"""
        filled = False
        for action_name, default_keys in self.DEFAULT_SHORTCUTS.items():
            if action_name not in shortcuts_config:
                shortcuts_config[action_name] = {"keys": default_keys}
                filled = True
        return filled

    def validate(self) -> List[str]:
        """校验配置完整性，返回缺失项警告列表"""
        warnings = []

        for action_name, display_name in self.ACTION_DEFINITIONS.items():
            if action_name not in self.shortcuts:
                warnings.append(f"'{action_name}' ({display_name}) 未配置，该功能无快捷键")
            elif not self.shortcuts[action_name].get('keys'):
                warnings.append(f"'{action_name}' ({display_name}) 的 keys 为空，该功能无快捷键")

        return warnings

    def bind_all(self, root: tk.Tk, callbacks: Dict[str, Callable]) -> None:
        """
        批量绑定所有快捷键到回调函数

        Args:
            root: tkinter 根窗口
            callbacks: 动作名称 -> 回调函数的映射
        """
        for action_name, shortcut_data in self.shortcuts.items():
            keys = shortcut_data.get('keys', [])
            callback = callbacks.get(action_name)

            if callback and keys:
                for key in keys:
                    root.bind(f"<{key}>", lambda e, cb=callback: cb())

    def unbind_all(self, root: tk.Tk) -> None:
        """批量解绑所有快捷键"""
        for action_name, shortcut_data in self.shortcuts.items():
            keys = shortcut_data.get('keys', [])
            for key in keys:
                try:
                    root.unbind(f"<{key}>")
                except tk.TclError:
                    pass  # 键未绑定，忽略

    def get_display_text(self) -> str:
        """生成状态栏显示文本"""
        parts = []
        for action_name, display_name in self.ACTION_DEFINITIONS.items():
            shortcut_data = self.shortcuts.get(action_name, {})
            keys = shortcut_data.get('keys', [])
            if keys:
                formatted_keys = [self._format_key(k) for k in keys]
                parts.append(f"[{'/'.join(formatted_keys)}]{display_name}")

        return ' '.join(parts)

    def _format_key(self, key: str) -> str:
        """格式化单个按键用于显示"""
        # 特殊键映射
        if key in self.KEY_DISPLAY_MAP:
            return self.KEY_DISPLAY_MAP[key]

        # Control-o -> Ctrl+O
        if key.startswith('Control-'):
            return 'Ctrl+' + key[8].upper()

        # Alt-x -> Alt+X
        if key.startswith('Alt-'):
            return 'Alt+' + key[4].upper()

        # Shift-x -> Shift+X
        if key.startswith('Shift-'):
            return 'Shift+' + key[6].upper()

        # 其他键保持原样
        return key
