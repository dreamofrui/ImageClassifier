# 快捷键配置系统实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 重构快捷键系统，使其完全由配置文件控制，支持多键映射和按键释放。

**Architecture:** 新增独立的 `ShortcutManager` 类管理所有快捷键逻辑，包括格式迁移、按键绑定、校验和显示。`ImageClassifier` 通过 `ShortcutManager` 代理所有快捷键操作。

**Tech Stack:** Python 3.x, tkinter, 无新增依赖

---

## Task 1: 创建 ShortcutManager 基础结构

**Files:**
- Create: `shortcut_manager.py`

**Step 1: 创建 ShortcutManager 类框架**

```python
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

    def load_from_config(self, shortcuts_config: Dict[str, Any]) -> tuple[bool, List[str]]:
        """
        从配置加载快捷键，自动迁移旧格式

        Args:
            shortcuts_config: shortcuts 配置字典

        Returns:
            (是否发生了迁移, 警告列表)
        """
        pass

    def _migrate_old_format(self, shortcuts_config: Dict[str, Any]) -> bool:
        """检测并迁移旧格式，返回是否发生了迁移"""
        pass

    def _fill_missing_defaults(self, shortcuts_config: Dict[str, Any]) -> bool:
        """补充缺失的默认配置，返回是否发生了补充"""
        pass

    def validate(self) -> List[str]:
        """校验配置完整性，返回缺失项警告列表"""
        pass

    def bind_all(self, root: tk.Tk, callbacks: Dict[str, Callable]) -> None:
        """批量绑定所有快捷键到回调函数"""
        pass

    def unbind_all(self, root: tk.Tk) -> None:
        """批量解绑所有快捷键"""
        pass

    def get_display_text(self) -> str:
        """生成状态栏显示文本"""
        pass

    def _format_key(self, key: str) -> str:
        """格式化单个按键用于显示"""
        pass
```

**Step 2: 验证文件创建成功**

运行: `python -c "from shortcut_manager import ShortcutManager; sm = ShortcutManager(); print('OK')"`
预期输出: `OK`

---

## Task 2: 实现配置加载和迁移逻辑

**Files:**
- Modify: `shortcut_manager.py`

**Step 1: 实现 `_migrate_old_format` 方法**

在 `ShortcutManager` 类中实现：

```python
def _migrate_old_format(self, shortcuts_config: Dict[str, Any]) -> bool:
    """检测并迁移旧格式，返回是否发生了迁移"""
    migrated = False
    for key, value in shortcuts_config.items():
        if isinstance(value, str):
            # 旧格式: "skip": "s" → 新格式: "skip": {"keys": ["s"]}
            shortcuts_config[key] = {"keys": [value]}
            migrated = True
    return migrated
```

**Step 2: 实现 `_fill_missing_defaults` 方法**

```python
def _fill_missing_defaults(self, shortcuts_config: Dict[str, Any]) -> bool:
    """补充缺失的默认配置，返回是否发生了补充"""
    filled = False
    for action_name, default_keys in self.DEFAULT_SHORTCUTS.items():
        if action_name not in shortcuts_config:
            shortcuts_config[action_name] = {"keys": default_keys}
            filled = True
    return filled
```

**Step 3: 实现 `load_from_config` 方法**

```python
def load_from_config(self, shortcuts_config: Dict[str, Any]) -> tuple[bool, List[str]]:
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
```

**Step 4: 验证迁移逻辑**

运行: `python -c "
from shortcut_manager import ShortcutManager
sm = ShortcutManager()

# 测试旧格式迁移
old_config = {'next': 'd', 'previous': 'a'}
migrated, warnings = sm.load_from_config(old_config)
print(f'Migrated: {migrated}')
print(f'next keys: {sm.shortcuts[\"next\"][\"keys\"]}')
print(f'refresh keys: {sm.shortcuts.get(\"refresh\", {}).get(\"keys\", \"NOT FOUND\")}')
"`
预期输出:
```
Migrated: True
next keys: ['d']
refresh keys: ['F5']
```

---

## Task 3: 实现校验逻辑

**Files:**
- Modify: `shortcut_manager.py`

**Step 1: 实现 `validate` 方法**

```python
def validate(self) -> List[str]:
    """校验配置完整性，返回缺失项警告列表"""
    warnings = []

    for action_name, display_name in self.ACTION_DEFINITIONS.items():
        if action_name not in self.shortcuts:
            warnings.append(f"'{action_name}' ({display_name}) 未配置，该功能无快捷键")
        elif not self.shortcuts[action_name].get('keys'):
            warnings.append(f"'{action_name}' ({display_name}) 的 keys 为空，该功能无快捷键")

    return warnings
```

**Step 2: 验证校验逻辑**

运行: `python -c "
from shortcut_manager import ShortcutManager
sm = ShortcutManager()

# 测试空配置
sm.shortcuts = {'next': {'keys': []}}
warnings = sm.validate()
print(f'Warnings: {warnings}')
"`
预期输出:
```
Warnings: ["'next' (下一张) 的 keys 为空，该功能无快捷键", "'previous' (上一张) 未配置，该功能无快捷键", ...]
```

---

## Task 4: 实现按键格式化和显示文本生成

**Files:**
- Modify: `shortcut_manager.py`

**Step 1: 实现 `_format_key` 方法**

```python
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
```

**Step 2: 实现 `get_display_text` 方法**

```python
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
```

**Step 3: 验证显示文本生成**

运行: `python -c "
from shortcut_manager import ShortcutManager
sm = ShortcutManager()

sm.load_from_config({
    'next': {'keys': ['d', 'Right', 'Down']},
    'previous': {'keys': ['a', 'Left', 'Up']},
    'skip': {'keys': []},  # 空，不显示
    'undo': {'keys': ['u']},
    'refresh': {'keys': ['F5']},
    'open_folder': {'keys': ['Control-o']},
    'exit': {'keys': ['Escape']}
})

print(sm.get_display_text())
"`
预期输出:
```
[d/→/↓]下一张 [a/←/↑]上一张 [u]撤销 [F5]刷新文件列表 [Ctrl+O]打开文件夹 [Esc]退出分类模式
```

---

## Task 5: 实现按键绑定和解绑

**Files:**
- Modify: `shortcut_manager.py`

**Step 1: 实现 `bind_all` 方法**

```python
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

    # 绑定分类键（如果有）
    # 注：分类键的绑定在 ImageClassifier 中单独处理

def unbind_all(self, root: tk.Tk) -> None:
    """批量解绑所有快捷键"""
    for action_name, shortcut_data in self.shortcuts.items():
        keys = shortcut_data.get('keys', [])
        for key in keys:
            try:
                root.unbind(f"<{key}>")
            except tk.TclError:
                pass  # 键未绑定，忽略
```

**Step 2: 添加用于测试的简单验证**

运行: `python -c "
import tkinter as tk
from shortcut_manager import ShortcutManager

root = tk.Tk()
root.withdraw()  # 隐藏窗口

sm = ShortcutManager()
sm.load_from_config({
    'next': {'keys': ['d']},
    'previous': {'keys': ['a']},
})

callbacks = {
    'next': lambda: print('next'),
    'previous': lambda: print('previous'),
}

sm.bind_all(root, callbacks)
print('Bind successful')
sm.unbind_all(root)
print('Unbind successful')
root.destroy()
"`
预期输出:
```
Bind successful
Unbind successful
```

---

## Task 6: 修改 ImageClassifier - 初始化和加载

**Files:**
- Modify: `image_classifier.py`

**Step 1: 添加 import 语句**

在文件顶部添加：

```python
from shortcut_manager import ShortcutManager
```

**Step 2: 在 `__init__` 中初始化 ShortcutManager**

修改 `ImageClassifier.__init__` 方法，在 `self.setup_ui()` 调用之前添加：

```python
# 初始化快捷键管理器
self.shortcut_manager = ShortcutManager()
self._init_shortcuts()
```

**Step 3: 添加 `_init_shortcuts` 方法**

在 `ImageClassifier` 类中添加新方法：

```python
def _init_shortcuts(self):
    """初始化快捷键配置，处理迁移和警告"""
    shortcuts_config = self.config.get('shortcuts', {})
    migrated, warnings = self.shortcut_manager.load_from_config(shortcuts_config)

    if migrated:
        # 将迁移后的配置写回 config
        self.config['shortcuts'] = shortcuts_config
        self._save_config()

    if warnings:
        self._show_shortcut_warnings(warnings, shortcuts_config)

def _save_config(self):
    """保存配置到文件"""
    # 注：需要通过 ConfigManager 保存
    pass

def _show_shortcut_warnings(self, warnings: List[str], shortcuts_config: Dict):
    """显示快捷键配置警告"""
    pass
```

---

## Task 7: 实现配置保存和警告对话框

**Files:**
- Modify: `image_classifier.py`

**Step 1: 实现 `_save_config` 方法**

需要访问 ConfigManager。修改 `ImageClassifier.__init__` 接收 config_manager：

```python
class ImageClassifier:
    def __init__(self, config: Dict, config_manager=None):
        self.config = config
        self.config_manager = config_manager
        # ... 其余代码
```

实现 `_save_config`：

```python
def _save_config(self):
    """保存配置到文件"""
    if self.config_manager:
        # 更新 config_manager 中的配置
        for key, value in self.config.items():
            if key != 'python_interpreter':  # 排除 python_interpreter
                self.config_manager.set(f'image_classifier.{key}', value)
        self.config_manager.save()
```

**Step 2: 实现 `_show_shortcut_warnings` 方法**

```python
def _show_shortcut_warnings(self, warnings: List[str], shortcuts_config: Dict):
    """显示快捷键配置警告对话框"""
    warning_text = "以下功能未配置快捷键：\n\n"
    warning_text += "\n".join([f"• {w}" for w in warnings])
    warning_text += "\n\n这些功能将不可用。"

    # 创建自定义对话框
    dialog = tk.Toplevel(self.root)
    dialog.title("快捷键配置警告")
    dialog.transient(self.root)
    dialog.grab_set()

    # 警告图标和文本
    tk.Label(dialog, text="⚠", font=('Arial', 24), fg='orange').pack(pady=(20, 5))
    tk.Label(dialog, text=warning_text, justify=tk.LEFT, padx=20).pack()

    # 按钮框架
    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=20)

    def on_continue():
        dialog.destroy()

    def on_restore():
        # 恢复缺失项的默认值
        for action_name, default_keys in ShortcutManager.DEFAULT_SHORTCUTS.items():
            if action_name not in shortcuts_config or not shortcuts_config[action_name].get('keys'):
                shortcuts_config[action_name] = {"keys": default_keys}

        # 重新加载配置
        self.shortcut_manager.load_from_config(shortcuts_config)
        self.config['shortcuts'] = shortcuts_config
        self._save_config()
        self.update_shortcuts_display()

        dialog.destroy()

    tk.Button(btn_frame, text="继续", command=on_continue, width=10).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="恢复默认配置", command=on_restore, width=12).pack(side=tk.LEFT, padx=5)

    # 居中显示
    dialog.update_idletasks()
    x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
    y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{x}+{y}")

    dialog.wait_window()
```

---

## Task 8: 修改 ImageClassifier - 绑定逻辑

**Files:**
- Modify: `image_classifier.py`

**Step 1: 修改 `bind_navigation_only` 方法**

找到 `bind_navigation_only` 方法（约第547行），替换为：

```python
def bind_navigation_only(self):
    """仅绑定导航键，用于预览模式"""
    self.unbind_keys()

    callbacks = {
        'next': self.next_image,
        'previous': self.previous_image,
        'skip': self.next_image,
        'refresh': self._refresh_file_list,
        'open_folder': self._open_in_explorer,
    }
    self.shortcut_manager.bind_all(self.root, callbacks)
```

**Step 2: 修改 `bind_keys` 方法**

找到 `bind_keys` 方法（约第566行），替换为：

```python
def bind_keys(self):
    """绑定所有快捷键，用于分类模式"""
    self.unbind_keys()

    callbacks = {
        'next': self.next_image,
        'previous': self.previous_image,
        'skip': self.next_image,
        'undo': self.undo_last_action,
        'refresh': self._refresh_file_list,
        'open_folder': self._open_in_explorer,
        'exit': self.quit_classification,
    }
    self.shortcut_manager.bind_all(self.root, callbacks)

    # 绑定分类键
    for key in self.key_bindings.keys():
        self.root.bind(f"<{key}>", lambda e, k=key: self.classify_image(k))
```

**Step 3: 修改 `unbind_keys` 方法**

找到 `unbind_keys` 方法，添加 ShortcutManager 的解绑：

```python
def unbind_keys(self):
    """解绑所有快捷键"""
    self.shortcut_manager.unbind_all(self.root)

    # 解绑分类键
    for key in self.key_bindings.keys():
        try:
            self.root.unbind(f"<{key}>")
        except tk.TclError:
            pass
```

---

## Task 9: 修改 ImageClassifier - 状态栏显示

**Files:**
- Modify: `image_classifier.py`

**Step 1: 修改 `update_shortcuts_display` 方法**

找到 `update_shortcuts_display` 方法（约第111行），替换为：

```python
def update_shortcuts_display(self):
    """更新状态栏快捷键显示"""
    # 获取快捷键显示文本
    shortcuts_text = self.shortcut_manager.get_display_text()

    # 分类键显示
    bindings_text = " | ".join([f"{k}: {v}" for k, v in self.key_bindings.items()])

    text = f"快捷键: {shortcuts_text}\n"
    if bindings_text:
        text += f"分类键: {bindings_text}"

    self.shortcut_label.config(text=text)
```

---

## Task 10: 修改 main.py 传递 config_manager

**Files:**
- Modify: `main.py`

**Step 1: 找到 ImageClassifier 的实例化位置**

读取 `main.py` 确认当前如何创建 `ImageClassifier`。

**Step 2: 传递 config_manager**

确保 `ImageClassifier` 能够访问 `ConfigManager` 实例以保存配置。

---

## Task 11: 更新配置文件格式

**Files:**
- Modify: `config.json`

**Step 1: 更新 shortcuts 为新格式**

将：
```json
"shortcuts": {
    "next": "d",
    "previous": "a",
    "skip": "s",
    "undo": "u"
}
```

改为：
```json
"shortcuts": {
    "next": { "keys": ["d", "Right", "Down"] },
    "previous": { "keys": ["a", "Left", "Up"] },
    "skip": { "keys": ["s"] },
    "undo": { "keys": ["u"] },
    "refresh": { "keys": ["F5"] },
    "open_folder": { "keys": ["Control-o"] },
    "exit": { "keys": ["Escape"] }
}
```

---

## Task 12: 更新 README 文档

**Files:**
- Modify: `README.md`

**Step 1: 更新快捷键配置说明**

找到快捷键相关的文档部分，更新为新格式说明：

```markdown
### 快捷键配置

在 `config.json` 中的 `image_classifier.shortcuts` 部分配置：

```json
"shortcuts": {
    "next": { "keys": ["d", "Right", "Down"] },
    "previous": { "keys": ["a", "Left", "Up"] },
    "skip": { "keys": ["s"] },
    ...
}
```

- `keys` 数组支持多个按键绑定同一功能
- 设置为空数组 `"keys": []` 可释放该按键

#### 按键命名规范
- 字母键：`a`, `b`, `c`...
- 方向键：`Up`, `Down`, `Left`, `Right`
- 功能键：`F1`-`F12`
- 组合键：`Control-o`, `Alt-x`, `Shift-s`
```

---

## Task 13: 集成测试

**Step 1: 测试旧配置迁移**

1. 将 `config.json` 中的 `shortcuts` 改回旧格式
2. 启动程序
3. 验证配置自动迁移为新格式

**Step 2: 测试多键绑定**

1. 配置 `next` 为 `["d", "Right", "Down"]`
2. 启动程序，进入分类模式
3. 分别按 `d`、`→`、`↓` 键，验证都能切换到下一张

**Step 3: 测试按键释放**

1. 将 `skip` 配置为 `{ "keys": [] }`
2. 启动程序
3. 验证 `s` 键不再触发跳过功能
4. 验证状态栏不显示跳过快捷键

**Step 4: 测试配置缺失警告**

1. 从 `config.json` 中删除 `skip` 配置
2. 启动程序
3. 验证弹出警告对话框
4. 点击"恢复默认配置"，验证配置被恢复

---

## 实现顺序总结

1. **Task 1-5**: 创建并完善 `ShortcutManager` 类（独立模块，可单独测试）
2. **Task 6-9**: 修改 `ImageClassifier` 集成 `ShortcutManager`
3. **Task 10**: 修改 `main.py` 传递依赖
4. **Task 11**: 更新配置文件
5. **Task 12**: 更新文档
6. **Task 13**: 集成测试
