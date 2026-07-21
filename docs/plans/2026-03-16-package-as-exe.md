# ARS 打包为 EXE 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 ARS 工具包打包成独立的 exe 文件，配合外部可编辑的配置文件，方便分发给其他用户使用。

**Architecture:** 使用 PyInstaller 将 Python 应用打包成单个 exe 文件。配置文件 `config.json` 放在 exe 同级目录，程序启动时自动检测并读取。这样用户可以直接修改配置文件来改变程序行为。

**Tech Stack:** Python 3.x, PyInstaller, tkinter, Pillow

---

## 前置准备

**当前项目结构:**
```
ARS/
├── main.py                 # 主入口
├── config.json            # 配置文件
├── config_manager.py      # 配置管理
├── shortcut_manager.py    # 快捷键管理
├── image_classifier.py    # 图片分类核心
├── requirements.txt       # 依赖 (仅 Pillow)
└── fruit_apple_food_1815.ico  # 图标
```

**打包后结构:**
```
发布包/
├── ARS.exe               # 主程序
├── config.json           # 用户可编辑的配置文件
└── README.txt            # 使用说明 (可选)
```

---

### Task 1: 修改配置管理器支持 exe 模式

**问题:** 当前 `config_manager.py` 使用相对路径 `"config.json"`，打包后 exe 的工作目录可能不是 exe 所在目录，导致找不到配置文件。

**Files:**
- Modify: `config_manager.py:8-9`

**Step 1: 修改 ConfigManager 支持自动检测 exe 路径**

修改 `config_manager.py`，添加获取 exe 实际路径的逻辑：

```python
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
```

**Step 2: 验证修改**

运行程序确保功能正常：
```bash
cd d:/code/vscode_code/ARS
python main.py
```
Expected: 程序正常启动，配置加载成功

**Step 3: 提交**

```bash
git add config_manager.py
git commit -m "feat: 支持 exe 打包模式的配置文件路径检测"
```

---

### Task 2: 安装 PyInstaller

**Files:**
- Modify: `requirements.txt`

**Step 1: 添加 PyInstaller 到开发依赖**

在 `requirements.txt` 中添加（作为开发依赖）：

```
Pillow>=10.0.0
pyinstaller>=6.0.0
```

**Step 2: 安装依赖**

```bash
cd d:/code/vscode_code/ARS
pip install -r requirements.txt
```

Expected: PyInstaller 安装成功

---

### Task 3: 创建 PyInstaller 配置文件 (.spec)

**Files:**
- Create: `ARS.spec`

**Step 1: 创建 .spec 文件**

创建 `ARS.spec` 文件：

```python
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 不嵌入 config.json，让用户可以修改
    ],
    hiddenimports=[
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ARS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='fruit_apple_food_1815.ico',  # 使用苹果图标
)
```

**Step 2: 提交**

```bash
git add ARS.spec
git commit -m "feat: 添加 PyInstaller 打包配置文件"
```

---

### Task 4: 创建构建脚本

**Files:**
- Create: `build.bat`

**Step 1: 创建 Windows 批处理构建脚本**

创建 `build.bat`：

```batch
@echo off
chcp 65001 > nul
echo ====================================
echo ARS 工具包 - 构建脚本
echo ====================================
echo.

echo [1/4] 清理旧的构建文件...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
echo 清理完成。
echo.

echo [2/4] 开始打包...
pyinstaller ARS.spec --clean
if %errorlevel% neq 0 (
    echo 打包失败！
    pause
    exit /b 1
)
echo 打包完成。
echo.

echo [3/4] 复制配置文件到输出目录...
copy /Y "config.json" "dist\config.json"
echo 配置文件已复制。
echo.

echo [4/4] 创建发布包...
cd dist
if exist "ARS_Release" rmdir /s /q "ARS_Release"
mkdir "ARS_Release"
move "ARS.exe" "ARS_Release\"
copy "..\config.json" "ARS_Release\"
echo.
echo ====================================
echo 构建成功！
echo 发布包位置: dist\ARS_Release\
echo 包含文件:
echo   - ARS.exe      (主程序)
echo   - config.json  (配置文件)
echo ====================================
echo.
pause
```

**Step 2: 提交**

```bash
git add build.bat
git commit -m "feat: 添加 Windows 构建脚本"
```

---

### Task 5: 测试打包结果

**Step 1: 运行构建脚本**

```bash
cd d:/code/vscode_code/ARS
./build.bat
```

Expected:
- 构建成功，无错误
- 生成 `dist/ARS_Release/` 目录
- 包含 `ARS.exe` 和 `config.json`

**Step 2: 测试 exe 运行**

1. 进入 `dist/ARS_Release/` 目录
2. 双击 `ARS.exe` 运行
3. 验证：
   - 程序正常启动
   - 图标显示正确（苹果图标）
   - 无控制台窗口
   - 配置文件被正确读取
   - 图片分类功能正常

**Step 3: 测试配置文件修改**

1. 修改 `dist/ARS_Release/config.json` 中的某个值（如 window_size）
2. 重新运行 `ARS.exe`
3. 验证配置更改生效

---

### Task 6: 更新 README 文档

**Files:**
- Modify: `README.md`

**Step 1: 添加打包相关说明**

在 README.md 中添加：

```markdown
## 开发与打包

### 开发环境运行

```bash
pip install -r requirements.txt
python main.py
```

### 打包为 EXE

运行构建脚本：
```bash
./build.bat
```

打包完成后，发布包位于 `dist/ARS_Release/` 目录。

### 发布包内容

- `ARS.exe` - 主程序
- `config.json` - 配置文件（用户可修改）

### 配置文件说明

配置文件 `config.json` 支持以下设置：

- `image_classifier.supported_formats`: 支持的图片格式
- `image_classifier.default_key_bindings`: 默认按键绑定
- `image_classifier.window_size`: 窗口大小 [宽, 高]
- `image_classifier.shortcuts`: 快捷键配置

用户可以直接编辑配置文件，程序启动时会自动读取。
```

**Step 2: 提交**

```bash
git add README.md
git commit -m "docs: 添加打包和配置文件使用说明"
```

---

### Task 7: 创建 .gitignore 排除构建产物

**Files:**
- Modify: `.gitignore` (如果存在) 或 Create: `.gitignore`

**Step 1: 添加构建产物到忽略列表**

```
# PyInstaller 构建产物
build/
dist/
*.spec.bak

# Python 缓存
__pycache__/
*.py[cod]
*$py.class
*.so

# 虚拟环境
venv/
.venv/
env/
```

**Step 2: 提交**

```bash
git add .gitignore
git commit -m "chore: 添加构建产物到 gitignore"
```

---

## 完成检查清单

- [ ] config_manager.py 支持自动检测 exe 路径
- [ ] PyInstaller 已安装
- [ ] ARS.spec 配置文件已创建
- [ ] build.bat 构建脚本已创建
- [ ] 打包测试成功
- [ ] exe 运行正常（无控制台、正确图标）
- [ ] 配置文件修改后生效
- [ ] README 文档已更新
- [ ] .gitignore 已配置

---

## 最终发布包结构

```
ARS_Release/
├── ARS.exe               # 主程序（约 15-30MB）
└── config.json           # 用户可编辑的配置文件
```

用户使用方式：
1. 将整个 `ARS_Release` 文件夹复制到任意位置
2. 双击 `ARS.exe` 运行
3. 如需修改默认配置，编辑 `config.json` 文件
