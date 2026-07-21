# ARS 工具集

高效、美观、鲁棒的工具集合，使用 miniforge 进行环境管理。

## 特性

- ✅ **高效性**: 快速处理，流畅的用户体验
- ✅ **美观性**: 现代化的深色主题 UI 设计
- ✅ **鲁棒性**: 完善的错误处理和异常管理

## 环境配置

### Python 解释器

项目使用 miniforge 环境管理，解释器路径在 `config.json` 中配置：

```json
{
    "python_interpreter": "D:\\miniforge3\\envs\\tool\\python.exe"
}
```

### 安装依赖

```bash
pip install -r requirements.txt
```

## 工具列表

### 1. 图片按键分类工具 📷

快速对文件夹中的图片进行分类，通过键盘按键直接将图片移动到对应文件夹。

#### 功能特点

- 🖼️ **可视化预览**: 自动调整图片大小以适应窗口
- ⌨️ **键盘快捷键**: 按键直接分类，无需拖拽
- 🔄 **撤销功能**: 支持撤销上一步操作
- 📁 **智能目标文件夹**: 自动设置为源文件夹的父目录，分类文件夹自动创建
- 🎨 **自定义绑定**: 支持任意按键与文件夹的绑定，支持中文文件夹名
- 🔢 **进度显示**: 实时显示分类进度
- 📦 **移动操作**: 图片采用移动而非复制，高效处理

#### 使用方法

1. 运行主程序：
   ```bash
   python main.py
   ```

2. 点击 "图片按键分类工具"

3. 选择源文件夹（包含待分类的图片）
   - 例如：选择 `ens/图片1` 文件夹
   - 目标文件夹会**自动设置为父目录** `ens/`
   - 分类文件夹将在 `ens/` 下自动创建（如不存在）

4. 配置按键绑定（可选）
   - 点击 "配置按键绑定"
   - 设置按键与文件夹的对应关系
   - **支持中文文件夹名**，例如：
     - 按键 "m" → 文件夹 "图片分类1"
     - 按键 "1" → 文件夹 "风景"
     - 按键 "2" → 文件夹 "人物"
   - 如需修改目标文件夹位置，点击 "修改目标文件夹"

5. 点击 "开始分类"

7. 使用快捷键：
   - **自定义按键**: 将图片分类到对应文件夹（可在"配置按键绑定"中设置）
   - **d/→/↓**: 下一张图片
   - **a/←/↑**: 上一张图片
   - **s**: 跳过当前图片
   - **u**: 撤销上一步操作
   - **F5**: 刷新文件列表
   - **Ctrl+O**: 打开文件夹
   - **Esc**: 退出分类模式

#### 配置说明

在 `config.json` 中的 `image_classifier` 部分可以配置：

```json
{
    "image_classifier": {
        "supported_formats": [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff"],
        "default_key_bindings": {
            "p": "PT",
            "q": "QK",
            "g": "GE",
            "m": "MA"
        },
        "window_size": [1200, 800],
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

- `supported_formats`: 支持的图片格式
- `default_key_bindings`: 默认的分类按键绑定
- `window_size`: 窗口大小
- `shortcuts`: 快捷键配置（支持多键映射）

#### 快捷键配置详解

快捷键配置使用新的对象格式，支持以下特性：

- **多键映射**: `keys` 数组支持为同一功能绑定多个按键
- **释放按键**: 设置 `"keys": []` 可禁用某功能的快捷键
- **自动迁移**: 旧格式 `"next": "d"` 会自动迁移为新格式

**按键命名规范**:
- 字母键：`a`, `b`, `c`...
- 方向键：`Up`, `Down`, `Left`, `Right`
- 功能键：`F1`-`F12`
- 组合键：`Control-o`, `Alt-x`, `Shift-s`

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

打包完成后，发布包位于 `dist/ImageClassifier_Release/` 目录。

### 发布包内容

```
ImageClassifier_Release/
├── ImageClassifier.exe  # 主程序
└── config.json          # 配置文件（用户可修改）
```

### 用户使用方式

1. 将 `ImageClassifier_Release` 文件夹复制到任意位置
2. 双击 `ImageClassifier.exe` 运行
3. 如需修改默认配置，编辑同目录下的 `config.json` 文件

## 项目结构

```
ARS/
├── main.py                 # 主入口
├── config.json            # 配置文件
├── config_manager.py      # 配置管理器
├── shortcut_manager.py    # 快捷键管理器
├── image_classifier.py    # 图片分类工具
├── ImageClassifier.spec   # PyInstaller 打包配置
├── build.bat              # Windows 构建脚本
├── requirements.txt       # 依赖包
└── README.md             # 说明文档
```

## 开发计划

- [x] 配置系统
- [x] 图片按键分类工具
- [ ] 更多工具待添加...

## 注意事项

1. 确保 miniforge 环境已正确安装
2. 图片分类操作会**移动**文件，请注意备份重要数据
3. 支持撤销操作，但仅保留当前会话的历史记录

## 许可证

MIT License
