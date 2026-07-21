# ARS 图片按键分类工具 API 文档

本文档面向 Next.js 前端和 Node.js 后端迁移开发，先记录当前 Python/Tkinter 桌面版的真实行为，再给出建议的 Web API 合约。当前项目本身没有 HTTP API，因此下文的 API 是迁移时建议实现的接口设计。

## 1. 工具背景

ARS 当前只有一个核心工具：图片按键分类工具。它用于批量整理本地文件夹中的图片，用户选择一个“源文件夹”，工具扫描其中的图片并逐张预览；用户按下分类键后，当前图片会被移动到“目标根目录”下对应的分类文件夹中。

典型使用场景：

- 人工快速复核大量图片。
- 按键直接把图片分到 `PT`、`QK`、`GE`、`MA`、`gray_ok` 等目录。
- 浏览、跳过、撤销、刷新文件列表。
- 鼠标缩放和平移查看细节。

重要约束：

- 分类操作是移动文件，不是复制文件。
- 撤销历史只保存在当前会话内，程序关闭后丢失。
- 源文件夹扫描是非递归扫描，只处理源目录第一层文件。
- 分类目录按需创建。
- 若目标文件重名，会自动追加 `_1`、`_2` 等后缀。

## 2. 当前项目架构

### 2.1 文件职责

| 文件 | 职责 |
| --- | --- |
| `main.py` | Tkinter 入口。加载 `config.json`，显示 ARS 工具集首页，点击按钮后启动图片分类器。 |
| `config_manager.py` | JSON 配置读取、点路径 `get/set`、保存配置。兼容开发模式与 PyInstaller 打包模式的应用目录定位。 |
| `shortcut_manager.py` | 快捷键配置加载、旧格式迁移、默认值补齐、校验、绑定/解绑、状态栏显示文本生成。 |
| `image_classifier.py` | 图片分类核心。负责 UI、源/目标目录、扫描图片、显示图片、分类移动、撤销、刷新、跳转、缩放和平移。 |
| `config.json` | 图片格式、默认分类键、窗口大小、快捷键、缩放延迟等运行配置。 |
| `build.bat` / `ImageClassifier.spec` | Windows/PyInstaller 打包配置，不参与业务运行逻辑。 |

### 2.2 桌面版运行流程

1. `main.py` 创建 `ConfigManager("config.json")`。
2. 用户点击“图片按键分类工具”。
3. `main.py` 调用 `config_manager.get_image_classifier_config()`，把 `image_classifier` 配置传给 `ImageClassifier`。
4. `ImageClassifier` 初始化状态、Tkinter 窗口、`ShortcutManager` 和 UI。
5. 用户选择源文件夹后：
   - `source_folder = 用户选择目录`
   - `target_folder = source_folder.parent`
   - 扫描源文件夹中的图片。
   - 进入预览模式，只绑定导航、刷新、打开文件夹等快捷键。
6. 用户点击“开始分类”后：
   - 若未配置会话内分类键，则使用 `default_key_bindings`。
   - 进入分类模式，绑定分类键、撤销、退出等快捷键。
7. 用户按分类键后，当前图片移动到目标分类目录，并从待处理列表移除。

## 3. 当前配置模型

当前 `config.json`：

```json
{
  "image_classifier": {
    "supported_formats": [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff"],
    "default_key_bindings": {
      "p": "PT",
      "q": "QK",
      "g": "GE",
      "m": "MA",
      "o": "gray_ok"
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
    },
    "zoom_end_delay": 150,
    "use_fast_zoom": true
  }
}
```

字段说明：

| 字段 | 类型 | 当前行为 |
| --- | --- | --- |
| `supported_formats` | `string[]` | 用于扫描图片扩展名。每个扩展名会同时匹配小写和大写形式。 |
| `default_key_bindings` | `Record<string,string>` | 默认分类键到分类文件夹名的映射。分类键必须是单字符。 |
| `window_size` | `[number, number]` | Tkinter 窗口宽高。Web 端可仅作为默认布局参考。 |
| `shortcuts` | `Record<string,{keys:string[]}>` | 操作快捷键。支持同一动作多个按键，空数组表示禁用快捷键。 |
| `zoom_end_delay` | `number` | Ctrl+滚轮缩放后延迟多少毫秒进行高质量重绘。 |
| `use_fast_zoom` | `boolean` | 配置存在，但当前 Python 代码未读取该字段；当前实现始终缩放中快速渲染、缩放结束高质量渲染。 |

支持的快捷键动作：

| 动作 | 含义 | 默认键 |
| --- | --- | --- |
| `next` | 下一张 | `d`, `Right`, `Down` |
| `previous` | 上一张 | `a`, `Left`, `Up` |
| `skip` | 跳过当前图，本质等同下一张 | `s` |
| `undo` | 撤销上一次移动 | `u` |
| `refresh` | 重新扫描源文件夹 | `F5` |
| `open_folder` | 打开源文件夹 | `Control-o` |
| `exit` | 退出分类模式，回到预览模式 | `Escape` |

旧格式兼容：

```json
{
  "next": "d"
}
```

启动时会迁移为：

```json
{
  "next": { "keys": ["d"] }
}
```

并补齐缺失动作的默认快捷键。

## 4. 输入、输出与状态

### 4.1 输入

| 输入 | 来源 | 说明 |
| --- | --- | --- |
| 配置文件 | `config.json` | 图片格式、默认分类键、快捷键等。 |
| 源文件夹 | 用户选择 | 包含待分类图片的本地目录。 |
| 目标根目录 | 自动或用户选择 | 默认是源文件夹父目录，也可手动改为其他目录。 |
| 分类键绑定 | 配置或用户弹窗输入 | 单字符按键到分类目录名。当前桌面版弹窗修改只影响当前会话，不写回 `config.json`。 |
| 导航/动作快捷键 | 配置 | 下一张、上一张、跳过、撤销、刷新、退出。 |
| 页码 | 用户输入 | 1 基页码，用于跳转到指定图片。 |
| 鼠标操作 | UI 事件 | Ctrl+滚轮缩放，左键拖拽平移。 |

### 4.2 输出

| 输出 | 说明 |
| --- | --- |
| 文件移动结果 | 图片被移动到 `targetFolder/categoryFolder/fileName`。 |
| 分类目录 | 分类时按需创建。 |
| 重名文件名 | 目标已存在时生成 `stem_1.ext`、`stem_2.ext`。 |
| 图片预览 | 当前图片按窗口适配显示，并支持缩放、平移。 |
| 会话状态 | 当前索引、总数、源/目标目录、快捷键显示、是否可撤销等。 |
| 撤销历史 | 当前会话内的移动记录。 |
| 配置变更 | 快捷键旧格式迁移或恢复默认配置时会写回 `config.json`。 |
| 错误/提示 | 无图片、文件不存在、加载失败、移动失败、页码非法等。 |

### 4.3 核心会话状态

建议 Node.js 后端以 session 为单位维护以下状态：

```ts
type ClassifierSession = {
  sessionId: string;
  mode: "preview" | "classification";
  sourceFolder: string | null;
  targetFolder: string | null;
  images: ImageItem[];
  currentIndex: number;
  keyBindings: Record<string, string>;
  shortcuts: Record<string, { keys: string[] }>;
  history: MoveHistoryItem[];
  preserveZoom: boolean;
  createdAt: string;
  updatedAt: string;
};

type ImageItem = {
  id: string;
  name: string;
  path: string;
  ext: string;
  sizeBytes?: number;
  mtimeMs?: number;
  width?: number;
  height?: number;
};

type MoveHistoryItem = {
  type: "move";
  sourcePath: string;
  targetPath: string;
  imageName: string;
  movedAt: string;
};
```

注意：Web 前端不应直接依赖绝对路径作为图片标识，建议后端生成 `image.id` 并通过 session + image id 访问图片流。

## 5. 关键实现细节

### 5.1 扫描图片

当前实现：

- 从 `source_folder` 第一层扫描，不递归子目录。
- 使用 `supported_formats` 逐个扩展名匹配。
- 对每个扩展名同时匹配小写与大写，例如 `.jpg` 和 `.JPG`。
- 使用 `set` 去重，然后 `sorted` 排序。
- 扫描后 `current_index = 0`。

建议 Node.js 复刻：

```ts
function scanImages(sourceFolder: string, supportedFormats: string[]): ImageItem[] {
  // 1. fs.readdir(sourceFolder, { withFileTypes: true })
  // 2. 只保留 file，不递归目录
  // 3. path.extname(name).toLowerCase() 匹配 supportedFormats lower-case 集合
  // 4. 按文件路径或文件名稳定排序
}
```

### 5.2 选择源/目标目录

当前行为：

- 选择源目录后自动设置 `target_folder = source_folder.parent`。
- 用户可手动修改目标根目录。
- 信息栏显示 `源: ... (N 张图片) | 目标: ...`。

Web 迁移建议：

- 前端负责输入或选择源路径。
- 后端负责规范化路径、校验目录存在、校验访问权限。
- 创建 session 时若没有传 `targetFolder`，后端自动取 `path.dirname(sourceFolder)`。

### 5.3 开始分类

当前行为：

- 必须有源目录和目标目录。
- 源目录中必须有图片。
- 如果当前会话没有 `key_bindings`，使用配置中的 `default_key_bindings`。
- 不会重置当前位置，保持当前预览到的图片。
- 进入分类模式后才绑定分类键。

Web 迁移建议：

- session 创建后默认为 `preview`。
- 调用 start 接口进入 `classification`。
- 分类接口只允许在 `classification` 模式下执行。

### 5.4 分类移动

当前行为：

1. 根据按键找到分类目录名：`folderName = keyBindings[key]`。
2. 目标分类目录：`targetFolder/folderName`。
3. 若目录不存在则创建。
4. 目标文件初始为同名文件。
5. 若重名，依次尝试 `stem_1.ext`、`stem_2.ext`。
6. 使用 `shutil.move` 移动文件。
7. 记录历史：`("move", sourcePath, targetPath)`。
8. 从 `images` 列表删除当前项。
9. 如果当前索引越界，则移动到最后一张。
10. 重新显示当前图片。

Node.js 伪代码：

```ts
async function classifyCurrentImage(session: ClassifierSession, key: string) {
  const folderName = session.keyBindings[key];
  if (!folderName) throw new ApiError("KEY_NOT_BOUND", "按键未绑定分类目录");

  const image = session.images[session.currentIndex];
  if (!image) throw new ApiError("NO_CURRENT_IMAGE", "当前没有可分类图片");
  if (!(await exists(image.path))) throw new ApiError("SOURCE_FILE_MISSING", "源文件不存在");

  const categoryDir = path.join(session.targetFolder!, folderName);
  await fs.mkdir(categoryDir, { recursive: true });

  const targetPath = await resolveConflictPath(categoryDir, image.name);
  await fs.rename(image.path, targetPath); // 跨盘移动时可 fallback 到 copy + unlink

  session.history.push({
    type: "move",
    sourcePath: image.path,
    targetPath,
    imageName: image.name,
    movedAt: new Date().toISOString()
  });

  session.images.splice(session.currentIndex, 1);
  if (session.currentIndex >= session.images.length && session.images.length > 0) {
    session.currentIndex = session.images.length - 1;
  }
}
```

冲突文件名算法：

```ts
// image.jpg -> image_1.jpg -> image_2.jpg
function resolveConflictPath(categoryDir: string, fileName: string): string {
  const ext = path.extname(fileName);
  const stem = path.basename(fileName, ext);
  let candidate = path.join(categoryDir, fileName);
  let counter = 1;
  while (existsSync(candidate)) {
    candidate = path.join(categoryDir, `${stem}_${counter}${ext}`);
    counter += 1;
  }
  return candidate;
}
```

### 5.5 撤销

当前行为：

- 只撤销当前会话内最后一次移动。
- 历史栈为空时提示“没有可撤销的操作”。
- 撤销时把 `targetPath` 移回 `sourcePath`。
- 撤销后把原路径插入 `images[current_index]`，不是原始排序位置。
- 当前实现没有为撤销目标路径冲突设计额外处理。

迁移建议：

- 保持与当前行为一致：只支持 LIFO 单步/多步连续撤销。
- 若 `sourcePath` 已存在，应返回明确错误 `UNDO_SOURCE_CONFLICT`，避免覆盖用户文件。
- 撤销历史如果要跨服务重启保留，需要额外持久化；否则按当前桌面版只保存在内存。

### 5.6 刷新文件列表

当前行为：

- 重新扫描源文件夹。
- 如果刷新前当前文件仍存在，则尽量定位到该文件的新索引。
- 如果当前文件不存在，则保持原索引位置，越界时取最后一张。
- 如果源文件夹已清空，清空预览和进度。
- 会提示刷新前后数量变化。

迁移建议：

- refresh 接口返回 `oldCount`、`newCount`、`currentImageChanged`。
- 前端根据返回状态刷新列表和预览。

### 5.7 文件存在性检查

当前实现会在显示和分类前检查当前文件是否存在：

- 如果文件被外部程序删除或移动，弹窗提示。
- 自动刷新文件列表。
- 本次显示/分类终止。

Web 迁移建议：

- 所有依赖当前图片的接口先校验文件仍存在。
- 不存在时返回 `SOURCE_FILE_MISSING`，并可自动执行 refresh 后返回新状态。

### 5.8 图片预览、缩放和平移

当前桌面版：

- 使用 Pillow 打开当前图片。
- 默认按 canvas 尺寸等比例适配。
- `zoomLevel` 初始为 `1.0`，Ctrl+滚轮按 `1.1` 倍缩放。
- 缩放范围：`0.1` 到 `10.0`。
- 缩放中使用较快的 BILINEAR，延迟后用 LANCZOS 高质量重绘。
- 左键拖拽修改 pan offset。
- “保持缩放”开启时，切图不重置缩放和平移。

Web 迁移建议：

- 图片解码和显示交给浏览器，后端只提供图片流和元数据。
- `zoomLevel`、`panOffset`、`preserveZoom` 可以由前端状态维护。
- 若需要服务端生成缩略图，可新增 thumbnail 接口，但不是当前桌面版必需能力。

## 6. 建议 API 合约

### 6.1 通用响应

成功响应建议统一返回：

```json
{
  "ok": true,
  "data": {}
}
```

错误响应：

```json
{
  "ok": false,
  "error": {
    "code": "SOURCE_FOLDER_NOT_FOUND",
    "message": "源文件夹不存在",
    "details": {}
  }
}
```

常见错误码：

| code | HTTP | 含义 |
| --- | --- | --- |
| `INVALID_REQUEST` | 400 | 参数格式错误。 |
| `SOURCE_FOLDER_NOT_FOUND` | 404 | 源目录不存在。 |
| `TARGET_FOLDER_NOT_FOUND` | 404 | 目标目录不存在且无法创建。 |
| `NO_IMAGES_FOUND` | 409 | 源目录没有支持格式的图片。 |
| `SESSION_NOT_FOUND` | 404 | 会话不存在或已过期。 |
| `NOT_IN_CLASSIFICATION_MODE` | 409 | 当前不在分类模式。 |
| `KEY_NOT_BOUND` | 400 | 分类键未绑定。 |
| `SOURCE_FILE_MISSING` | 409 | 当前图片文件已被外部变更。 |
| `MOVE_FAILED` | 500 | 文件移动失败。 |
| `NO_UNDO_HISTORY` | 409 | 没有可撤销操作。 |
| `UNDO_SOURCE_CONFLICT` | 409 | 撤销目标位置已有文件。 |
| `IMAGE_LOAD_FAILED` | 415 | 图片无法读取或格式损坏。 |

### 6.2 会话状态响应

多个接口都应返回最新 session 状态：

```json
{
  "sessionId": "cls_01HX...",
  "mode": "classification",
  "sourceFolder": "D:\\photos\\pending",
  "targetFolder": "D:\\photos",
  "total": 128,
  "currentIndex": 0,
  "currentPage": 1,
  "currentImage": {
    "id": "img_01HX...",
    "name": "0001.jpg",
    "ext": ".jpg",
    "sizeBytes": 345678,
    "width": 1920,
    "height": 1080,
    "previewUrl": "/api/classifier/sessions/cls_01HX/images/img_01HX/file"
  },
  "keyBindings": {
    "p": "PT",
    "q": "QK",
    "g": "GE",
    "m": "MA",
    "o": "gray_ok"
  },
  "shortcuts": {
    "next": { "keys": ["d", "Right", "Down"] },
    "previous": { "keys": ["a", "Left", "Up"] }
  },
  "canUndo": true,
  "historyCount": 3,
  "message": null
}
```

### 6.3 获取配置

`GET /api/image-classifier/config`

返回当前配置、快捷键显示文本和配置校验警告。

响应：

```json
{
  "ok": true,
  "data": {
    "config": {
      "supportedFormats": [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff"],
      "defaultKeyBindings": {
        "p": "PT",
        "q": "QK",
        "g": "GE",
        "m": "MA",
        "o": "gray_ok"
      },
      "shortcuts": {
        "next": { "keys": ["d", "Right", "Down"] }
      },
      "zoomEndDelay": 150
    },
    "warnings": [],
    "shortcutDisplayText": "[d/→/↓]下一张 [a/←/↑]上一张"
  }
}
```

### 6.4 更新配置

`PUT /api/image-classifier/config`

用于持久化默认配置。它对应编辑 `config.json`，不同于会话内临时修改分类键。

请求：

```json
{
  "defaultKeyBindings": {
    "1": "风景",
    "2": "人物"
  },
  "shortcuts": {
    "next": { "keys": ["d", "Right"] },
    "skip": { "keys": [] }
  }
}
```

响应返回更新后的配置。后端应校验：

- 分类键必须为单字符。
- 分类文件夹名不能为空。
- `shortcuts.*.keys` 必须是字符串数组。
- 建议检测分类键和动作快捷键冲突，并返回 warnings。当前桌面版未禁止冲突，分类键会覆盖同键动作快捷键。

### 6.5 创建分类会话

`POST /api/classifier/sessions`

请求：

```json
{
  "sourceFolder": "D:\\photos\\pending",
  "targetFolder": null,
  "keyBindings": null
}
```

行为：

- 校验源目录存在。
- 未提供 `targetFolder` 时，使用源目录父目录。
- 扫描图片。
- 创建 `preview` 模式会话。
- 若提供 `keyBindings`，作为当前会话分类键；否则先为空，开始分类时再加载默认值。

响应：

```json
{
  "ok": true,
  "data": {
    "session": {
      "sessionId": "cls_01HX...",
      "mode": "preview",
      "sourceFolder": "D:\\photos\\pending",
      "targetFolder": "D:\\photos",
      "total": 128,
      "currentIndex": 0,
      "currentPage": 1,
      "currentImage": {
        "id": "img_01HX...",
        "name": "0001.jpg",
        "previewUrl": "/api/classifier/sessions/cls_01HX/images/img_01HX/file"
      },
      "canUndo": false,
      "historyCount": 0
    }
  }
}
```

### 6.6 获取会话状态

`GET /api/classifier/sessions/:sessionId`

返回当前 session 状态。前端刷新页面后可用它恢复界面。

### 6.7 修改目标根目录

`PATCH /api/classifier/sessions/:sessionId/target`

请求：

```json
{
  "targetFolder": "D:\\photos\\classified"
}
```

行为：

- 更新当前会话目标根目录。
- 不移动已分类文件。
- 后续分类写入新目标目录。

### 6.8 更新会话分类键

`PUT /api/classifier/sessions/:sessionId/bindings`

对应桌面版“配置按键绑定”弹窗。默认只影响当前会话，不写入全局配置。

请求：

```json
{
  "keyBindings": {
    "1": "风景",
    "2": "人物",
    "3": "其他"
  }
}
```

校验：

- key 必须为单字符。
- folderName trim 后不能为空。
- key 不能重复。
- 建议返回 shortcut conflict warnings。

### 6.9 开始分类

`POST /api/classifier/sessions/:sessionId/start`

行为：

- 校验 session 有源目录、目标目录和图片。
- 若会话 `keyBindings` 为空，加载配置的 `defaultKeyBindings`。
- 设置 `mode = "classification"`。
- 保持当前 `currentIndex`。

响应返回最新 session。

### 6.10 获取当前图片文件

`GET /api/classifier/sessions/:sessionId/images/:imageId/file`

返回图片二进制流。

要求：

- `imageId` 必须属于当前 session。
- 后端不能接受任意文件路径参数直读文件，避免目录穿越。
- 建议设置 `Content-Type`，如 `image/jpeg`、`image/png`。
- 文件不存在时返回 `SOURCE_FILE_MISSING`。

可选缩略图接口：

`GET /api/classifier/sessions/:sessionId/images/:imageId/thumbnail?maxWidth=512`

这不是当前桌面版必需能力，只有在大图性能不足时再实现。

### 6.11 导航

`POST /api/classifier/sessions/:sessionId/navigate`

请求：

```json
{
  "action": "next"
}
```

或：

```json
{
  "action": "jump",
  "page": 12
}
```

支持动作：

| action | 行为 |
| --- | --- |
| `next` | 如果不是最后一张，`currentIndex += 1`。 |
| `previous` | 如果不是第一张，`currentIndex -= 1`。 |
| `skip` | 等同 `next`，不移动文件。 |
| `jump` | 使用 1 基页码跳转，必须在 `1..total`。 |

响应返回最新 session。

### 6.12 分类当前图片

`POST /api/classifier/sessions/:sessionId/classify`

请求：

```json
{
  "key": "p"
}
```

行为：

- 必须处于 `classification` 模式。
- `key` 必须存在于 `keyBindings`。
- 移动当前图片到 `targetFolder/keyBindings[key]`。
- 重名时追加序号。
- 更新 history、images、currentIndex。

响应：

```json
{
  "ok": true,
  "data": {
    "moved": {
      "sourcePath": "D:\\photos\\pending\\0001.jpg",
      "targetPath": "D:\\photos\\PT\\0001.jpg",
      "category": "PT"
    },
    "session": {}
  }
}
```

### 6.13 撤销

`POST /api/classifier/sessions/:sessionId/undo`

行为：

- 弹出最后一条 `history`。
- 把 `targetPath` 移回 `sourcePath`。
- 将图片插入当前 `currentIndex`。
- 返回最新 session。

响应：

```json
{
  "ok": true,
  "data": {
    "restored": {
      "sourcePath": "D:\\photos\\pending\\0001.jpg",
      "targetPath": "D:\\photos\\PT\\0001.jpg"
    },
    "session": {}
  }
}
```

### 6.14 刷新文件列表

`POST /api/classifier/sessions/:sessionId/refresh`

行为复刻桌面版：

- 记录刷新前当前文件。
- 重新扫描。
- 当前文件仍存在则定位到该文件。
- 当前文件不存在则保持索引位置并做边界修正。

响应：

```json
{
  "ok": true,
  "data": {
    "oldCount": 128,
    "newCount": 127,
    "currentImageStillExists": false,
    "session": {}
  }
}
```

### 6.15 退出分类模式

`POST /api/classifier/sessions/:sessionId/exit`

行为：

- 设置 `mode = "preview"`。
- 不清空图片列表。
- 不重置当前索引。
- 不清空 history。

### 6.16 删除会话

`DELETE /api/classifier/sessions/:sessionId`

行为：

- 释放服务端内存状态。
- 不移动任何文件。
- 当前桌面版关闭程序后撤销历史丢失，Web 端删除 session 可视为同类行为。

### 6.17 打开系统文件夹

当前桌面版 `Ctrl+O` 会调用系统文件管理器打开源文件夹。

Web 迁移建议：

- 纯浏览器 Web 不应默认提供“让服务器打开本机资源管理器”的能力。
- 如果部署形态是本机 Electron/Tauri/本地 Node 工具，可提供：

`POST /api/classifier/sessions/:sessionId/open-folder`

后端调用 `explorer`、`open` 或 `xdg-open`。该接口必须限制为本机可信环境。

## 7. 前端实现要点

- 第一屏应是实际工具界面，不需要营销页。
- 前端维护键盘事件，把浏览器 `KeyboardEvent.key` 映射到后端配置的 key 命名。
- 动作快捷键由前端触发对应 API：导航、刷新、撤销、退出。
- 分类键触发 `/classify`。
- 当前桌面版中分类键如果和动作快捷键冲突，分类键后绑定，会覆盖动作快捷键。Web 端建议在 UI 上提示冲突。
- 跳转页码使用 1 基展示，后端状态使用 0 基 `currentIndex`。
- 缩放、平移、保持缩放建议完全在前端实现。
- 文件移动是破坏性操作，开始分类前应明确提示“移动而非复制”。
- 当前图片被外部改动时，前端应展示后端返回的错误，并触发或提示刷新。

## 8. 后端实现要点

- 使用 session 隔离不同用户或不同分类任务。
- 所有文件路径必须 `path.resolve` 后校验，避免目录穿越。
- 如果是多人 Web 服务，应增加工作区 allowlist，不能允许任意读取服务器磁盘。
- 图片流接口只能访问 session 内登记过的 image id。
- 文件移动优先用 `fs.rename`；跨磁盘失败时 fallback 到 copy + unlink。
- 分类目录创建用 `fs.mkdir(categoryDir, { recursive: true })`。
- 文件名冲突逻辑必须和桌面版一致。
- 撤销不要覆盖已存在文件；当前桌面版未处理该情况，Node 版建议返回冲突错误。
- session 历史默认内存保存即可；如果产品要求刷新服务后可撤销，需要持久化 history。
- 配置修改与会话内绑定修改要分开：全局配置写入文件，会话绑定只影响当前 session。

## 9. 迁移优先级建议

1. 配置读取与快捷键模型。
2. 创建 session、扫描图片、返回当前图片状态。
3. 图片流预览。
4. 开始分类与按键移动文件。
5. 导航、跳转、跳过。
6. 撤销。
7. 刷新文件列表与外部变更处理。
8. 会话内分类键编辑。
9. 全局配置持久化。
10. 可选：缩略图、打开系统文件夹、跨重启恢复历史。

