# 快捷键配置系统重设计

## 背景

当前快捷键配置存在以下问题：
1. 代码中存在硬编码的 fallback 值（如 `'s'`, `'d'`, `'a'`），用户无法通过删除配置来"释放"按键
2. 方向键、系统快捷键（F5、Ctrl+O、Escape）完全硬编码，不可配置
3. 配置文件与实际行为不一致，影响可维护性

## 目标

1. **完全由配置文件控制** - 所有快捷键绑定均可通过配置文件管理
2. **支持多键映射** - 一个功能可绑定多个按键
3. **允许释放按键** - 用户可以删除某项配置，释放按键给其他功能
4. **自动迁移** - 旧配置格式自动升级为新格式
5. **友好的用户提示** - 配置缺失时警告但允许继续运行

---

## 设计详情

### 1. 配置文件结构

#### 新的 `shortcuts` 配置格式

```json
{
    "image_classifier": {
        "shortcuts": {
            "next": { "keys": ["d", "Right", "Down"] },
            "previous": { "keys": ["a", "Left", "Up"] },
            "skip": { "keys": ["s"] },
            "undo": { "keys": ["u"] },
            "refresh": { "keys": ["F5"] },
            "open_folder": { "keys": ["Control-o"] },
            "exit": { "keys": ["Escape"] }
        }
    }
}
```

#### 设计要点

- **统一使用对象格式** - 每个快捷键是一个对象，`keys` 数组支持多个按键
- **允许空数组** - `"keys": []` 表示该功能无按键绑定（释放按键）
- **单键简写兼容** - 迁移后仍支持 `"next": "d"` 的简写形式，内部自动转换

#### 按键命名规范

使用 tkinter 标准命名：
- 字母键：`a`, `b`, `c`...
- 方向键：`Up`, `Down`, `Left`, `Right`
- 功能键：`F1`-`F12`
- 组合键：`Control-o`, `Alt-x`, `Shift-s`

---

### 2. 代码架构变更

#### 新增 `ShortcutManager` 类

```
ARS/
├── shortcut_manager.py    # 新增：快捷键管理器
├── config_manager.py      # 现有：配置读取
├── image_classifier.py    # 修改：使用 ShortcutManager
└── config.json            # 修改：新格式
```

#### `ShortcutManager` 职责

| 方法 | 功能 |
|------|------|
| `load_from_config(config)` | 从配置加载快捷键，处理格式转换 |
| `migrate_old_format(shortcuts)` | 检测并迁移旧格式 |
| `bind_all(root, callbacks)` | 批量绑定所有快捷键到回调函数 |
| `unbind_all(root)` | 批量解绑 |
| `get_display_text()` | 生成状态栏显示文本 |
| `validate()` | 校验配置完整性，返回缺失项列表 |

#### 与 `ImageClassifier` 的交互

```python
# image_classifier.py 中的使用方式
class ImageClassifier:
    def __init__(self, ...):
        self.shortcut_manager = ShortcutManager()
        shortcuts_config = self.config.get('shortcuts', {})

        # 加载并迁移
        migrated, warnings = self.shortcut_manager.load_from_config(shortcuts_config)
        if migrated:
            self.config.set('shortcuts', shortcuts_config)
            self.config.save()
        if warnings:
            self._show_config_warnings(warnings)

    def bind_keys(self):
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
```

---

### 3. 启动校验与警告机制

#### 校验流程

程序启动时，`ShortcutManager.validate()` 检查配置完整性：

```python
def validate(self) -> list[str]:
    """返回缺失或无效的配置项警告列表"""
    warnings = []

    for action_name in self.ACTION_DEFINITIONS:
        if action_name not in self.shortcuts:
            warnings.append(f"'{action_name}' 未配置，该功能无快捷键")
        elif not self.shortcuts[action_name].get('keys'):
            warnings.append(f"'{action_name}' 的 keys 为空，该功能无快捷键")

    return warnings
```

#### 功能定义（内置）

```python
ACTION_DEFINITIONS = {
    'next': '下一张',
    'previous': '上一张',
    'skip': '跳过',
    'undo': '撤销',
    'refresh': '刷新文件列表',
    'open_folder': '打开文件夹',
    'exit': '退出分类模式',
}
```

#### 启动时的用户提示

```
┌─────────────────────────────────────────┐
│  ⚠ 快捷键配置警告                        │
├─────────────────────────────────────────┤
│  以下功能未配置快捷键：                   │
│  • skip - 跳过                          │
│  • refresh - 刷新文件列表                │
│                                         │
│  这些功能将不可用。是否继续？             │
│                                         │
│  [继续]  [恢复默认配置]                   │
└─────────────────────────────────────────┘
```

#### 选项说明

| 按钮 | 行为 |
|------|------|
| **继续** | 忽略警告，正常启动（缺失功能无快捷键） |
| **恢复默认配置** | 将缺失项恢复为默认值，保存配置文件，然后启动 |

---

### 4. 自动迁移机制

#### 迁移触发时机

程序启动时，`ShortcutManager.load_from_config()` 检测配置格式：

```python
def load_from_config(self, shortcuts_config: dict) -> tuple[bool, list[str]]:
    """
    返回: (是否发生了迁移, 警告列表)
    """
    migrated = False

    # 检测旧格式并迁移
    for key, value in shortcuts_config.items():
        if isinstance(value, str):
            # 旧格式: "skip": "s" → 新格式: "skip": {"keys": ["s"]}
            shortcuts_config[key] = {"keys": [value]}
            migrated = True

    # 补充缺失的默认配置
    for action_name, default_keys in self.DEFAULT_SHORTCUTS.items():
        if action_name not in shortcuts_config:
            shortcuts_config[action_name] = {"keys": default_keys}
            migrated = True

    self.shortcuts = shortcuts_config
    warnings = self.validate()

    return migrated, warnings
```

#### 默认快捷键定义

```python
DEFAULT_SHORTCUTS = {
    'next': ['d', 'Right', 'Down'],
    'previous': ['a', 'Left', 'Up'],
    'skip': ['s'],
    'undo': ['u'],
    'refresh': ['F5'],
    'open_folder': ['Control-o'],
    'exit': ['Escape'],
}
```

#### 迁移示例

**旧配置：**
```json
"shortcuts": {
    "next": "d",
    "previous": "a"
}
```

**迁移后：**
```json
"shortcuts": {
    "next": { "keys": ["d"] },
    "previous": { "keys": ["a"] },
    "skip": { "keys": ["s"] },
    "undo": { "keys": ["u"] },
    "refresh": { "keys": ["F5"] },
    "open_folder": { "keys": ["Control-o"] },
    "exit": { "keys": ["Escape"] }
}
```

---

### 5. 状态栏显示与按键符号

#### 多键显示格式

状态栏显示时，多个按键用 `/` 分隔，方向键用箭头符号表示：

```python
def get_display_text(self) -> str:
    parts = []
    for action_name, display_name in self.ACTION_DEFINITIONS.items():
        keys = self.shortcuts.get(action_name, {}).get('keys', [])
        if keys:
            formatted_keys = [self._format_key(k) for k in keys]
            parts.append(f"[{'/'.join(formatted_keys)}]{display_name}")
    return ' '.join(parts)
```

#### 按键格式化规则

| 原始值 | 显示为 |
|--------|--------|
| `Up` | `↑` |
| `Down` | `↓` |
| `Left` | `←` |
| `Right` | `→` |
| `Control-o` | `Ctrl+O` |
| `Escape` | `Esc` |
| `F5` | `F5` |
| `a`, `d`, `s` | `a`, `d`, `s` |

#### 显示效果示例

**配置：**
```json
"next": { "keys": ["d", "Right", "Down"] },
"previous": { "keys": ["a", "Left", "Up"] },
"skip": { "keys": [] },
"open_folder": { "keys": ["Control-o"] }
```

**状态栏显示：**
```
[d/→/↓]下一张 [a/←/↑]上一张 [u]撤销 [F5]刷新 [Ctrl+O]打开文件夹 [Esc]退出分类模式
```

注意：`skip` 因 `keys` 为空，不显示在状态栏中。

---

## 实现清单

### 新增文件
- [ ] `shortcut_manager.py` - 快捷键管理器

### 修改文件
- [ ] `config.json` - 更新 shortcuts 格式
- [ ] `image_classifier.py` - 使用 ShortcutManager
- [ ] `README.md` - 更新文档

### 测试要点
- [ ] 旧配置自动迁移
- [ ] 多键绑定正常工作
- [ ] 空键配置释放按键
- [ ] 状态栏显示正确
- [ ] 配置缺失警告正常弹出
