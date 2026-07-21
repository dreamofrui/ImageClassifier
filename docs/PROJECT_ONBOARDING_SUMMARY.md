# ARS 项目新人接手总结

## Background

ARS 是一个 Windows 本地 Python 桌面工具，目前核心产品是“图片标注工作台”。它面向长期批量处理图片的标注人员：用户选择一个本地图片文件夹后，通过键盘分类键或右侧分类按钮，把当前图片移动到目标分类文件夹。

当前业务场景不是 AI 自动标注，也不是 Web 服务。它是一个本地文件操作工具，核心价值是让人工标注人员能快速浏览、缩放、跳转、分类、撤销，并且在需要时用更正式的界面给领导演示。

显式不在当前范围内的内容：

- LLM 对话、TTS 语音、图像生成。
- 自动分类模型、模型训练、云同步、多用户协作。
- Web API、浏览器前端、服务端会话管理。
- 营销首页或独立展示页。`Presentation` 只是工作台里的展示模式。

这个项目正在从旧 Tkinter 工具迁移到 PySide6/Qt 工作台。新人接手时必须先确认当前主线，否则容易改到旧入口或旧 UI。

## Current Status

当前主线是 Qt 工作台：

- 打包入口：`ImageClassifier.spec` 使用 `qt_main.py`。
- 程序入口：`qt_main.py` 创建 `QApplication`，加载 `ConfigManager()`，打开 `AnnotationWorkbench`。
- 主 UI：`qt_workbench.py`。
- 图片查看器：`qt_image_viewer.py`。
- 核心文件操作：`classifier_core.py`。

当前稳定可依赖的能力：

- 非递归扫描 Source 文件夹中的图片。
- Source 选定后，Target 在未手动选择前会跟随 Source 文件夹本身。
- 支持手动选择 Target；一旦用户手动选择 Target，本次运行期间后续切换 Source 不再覆盖 Target。
- 支持队列、跳转、上一张、下一张、跳过、刷新。
- 支持 Queue 文件名搜索：`Find` 按钮和 Enter 触发；输入带扩展名时按完整文件名忽略大小写匹配，输入不带扩展名时按文件名 stem 忽略大小写匹配。
- 支持 Queue `Back` 最近 5 条 LIFO 回退历史，覆盖搜索、队列点击、序号 Jump、上一张、下一张、Skip 等导航入口。
- 支持鼠标滚轮切换上一张/下一张，`Ctrl+滚轮` 缩放，拖动平移，Fit，双击适配窗口，Keep Zoom。
- 支持约 `1.2x fit` 以上切换锐利显示，降低高倍放大模糊。
- 支持按键方案 `binding_profiles` 的创建、切换、编辑、删除和持久化。
- 分类按键区分大小写：例如 `p` 和 `P` 是两个不同分类键；右侧分类按钮的 key cap 会保留原始大小写，Qt 快捷键注册中小写字母走普通字母键，大写字母走 `Shift+字母`。
- `Keys` 设置保存前会校验配置；不合规时弹提示并保持弹窗打开，不写入配置。
- 支持分类键和右侧按钮分类。
- 右侧 `Classify` 分类按钮支持 `1`–`4` 列下拉选择；切换结果持久化到 `image_classifier.classification_columns`，旧配置缺省为单列。
- 右侧 `LinkXML` 开关控制分类时是否连带移动同名 `.xml`；切换结果持久化到 `image_classifier.move_xml_pairs`，旧配置缺省为关闭。
- 分类是移动文件，不是复制。
- 目标文件冲突时自动追加 `_1`、`_2`。
- 支持当前会话内 LIFO 撤销。
- 移动和图片加载使用 Qt worker/thread，避免阻塞 UI 主线程。
- 发布包包含 `ImageClassifier.exe`、`config.json`、`USER_GUIDE.md`。

仍在过渡或需要谨慎判断的区域：

- `main.py` 和 `image_classifier.py` 仍是旧 Tkinter 路线，当前打包已经不走它们。
- `shortcut_manager.py` 主要服务旧 Tkinter 路线；Qt 工作台自己注册 `QShortcut`。
- `README.md` 和 `docs/image-classifier-api.md` 存在历史信息或编码显示问题，不能优先当事实来源。
- `docs/specs/ui-redesign.md` 中仍有一条旧合同写“Target 默认 source_folder.parent”，但当前代码和测试已经改为 Target 未手动选择前跟随 Source。

最直接的后续方向：

- 继续以 Qt 工作台为主线维护。
- 如果改 UI，优先改 `qt_workbench.py`、`qt_image_viewer.py`、`qt_theme.py`。
- 如果改文件移动、扫描、撤销、冲突命名，优先改 `classifier_core.py` 并补测试。
- 如果改按键方案持久化，必须同步关注 `binding_profiles.py`、`config.json` 和 Qt 工作台保存逻辑。

## 2026-06-05 / 6.5 Feature Handoff

6.5 的 Queue 搜索、`Back`、`Keys` 排序相关开发已经完成，不再作为待开发项处理。以下两个文档保留为设计和实施记录：

- 设计规格：`docs/superpowers/specs/2026-06-05-queue-search-key-order-design.md`。
- 实施计划：`docs/superpowers/plans/2026-06-05-queue-search-key-order.md`。

注意：计划文档中的早期表述包含“单层 Back”和“必须输入完整扩展名”的旧约束。后续根据用户反馈已调整，当前事实以 `qt_workbench.py` 和 `tests/test_qt_workbench.py` 为准。

已完成功能 1：左侧 Queue 文件名搜索与 `Back`

- 左侧 `Queue` 文件列表上方有搜索输入框，placeholder 为 `Filename`。
- 搜索输入框右侧是 `Find` 按钮；点击 `Find` 和按 Enter 都会触发搜索。
- 输入包含扩展名时，按完整文件名精确匹配、忽略大小写，例如 `b.jpg` 可匹配 `B.JPG`。
- 输入不包含扩展名时，按 stem 精确匹配、忽略大小写，例如 `ss` 可匹配当前队列中的 `ss.jpg`、`ss.png`、`ss.bmp` 等图片文件。
- 搜索只跳转当前图片，不过滤 Queue 列表。
- 搜索未命中时保持当前位置不变，并在状态栏提示未找到。
- `Back` 按钮位于 Queue header 行，不占用搜索输入框右侧位置。
- `Back` 维护最近 5 条 LIFO 回退历史，不是单层历史。
- 搜索、队列点击、序号 Jump、上一张、下一张、Skip 等成功改变当前图片的导航都会记录上一个位置。
- 如果回退历史中的图片已经因为刷新、分类移动等原因不在当前队列里，`Back` 会清空失效历史并提示不可用，不猜测替代目标。

已完成功能 2：`Keys` 弹窗按键映射拖拽排序与可操作性优化

- `Keys` 弹窗的映射行已经从静态 grid 改为可排序的 `QListWidget` 行列表。
- 行左侧使用紧凑抓手样式 `::` 和 tooltip，不再显示 `Drag` 文本。
- 映射行高度、内边距和行间距已压缩，弹窗最小尺寸为 `780x520`，避免控件被挤压到无法操作。
- 拖拽排序只改变弹窗内临时顺序；点击 `Save` 后才写入 `config.json`。
- 点击 `Cancel` 或右上角 `X` 会丢弃本次弹窗内所有变化，不写入配置。
- 点击 `Save` 时会先在弹窗内校验 rows；校验失败会弹提示并保持 `Keys` 弹窗打开，直到用户修正后才能保存。
- `Keys` 校验规则：空白行会被忽略；非空行必须同时有单字符 Key 和 Target Folder；同一个 Key 不能重复；不同 Key 不能指向完全同名的 Target Folder；不同 Key 也不能指向仅大小写不同的 Target Folder，例如 `pt` 和 `PT` 会被拒绝。
- 大小写 Key 本身允许共存，例如 `p` 和 `P` 可以对应不同分类，但目标文件夹名必须避免同名或仅大小写不同，防止 Windows 文件系统下分类目录歧义。
- 保存时按当前视觉顺序重建 active profile 的映射。
- 保存后右侧 `Classify` 按钮顺序、快捷键注册顺序、下次打开 `Keys` 的展示顺序都会跟随保存后的顺序。
- 持久化仍通过既有配置路径完成，并保持 `binding_profiles`、`active_binding_profile`、`default_key_bindings` 同步。
- 没有新增配置 schema；继续依赖 Python dict 的插入顺序表达映射顺序。
- 拖拽移动映射行后会清理选中高亮，避免绿色选中行或拖拽阴影残留影响阅读。
- 映射数量较多时，`Keys` 弹窗会按行数自动增高并受屏幕高度限制；映射列表隐藏垂直滚动条但保留滚轮滚动能力。

相关验证覆盖：

- `tests/test_qt_workbench.py` 已覆盖 Queue 搜索的完整文件名匹配、无扩展名 stem 匹配、`Find` 按钮触发和 Enter 触发。
- `tests/test_qt_workbench.py` 已覆盖 `Find`/`Back` 按钮尺寸一致性、Queue header 行对齐相关结构。
- `tests/test_qt_workbench.py` 已覆盖 `Back` 最近 5 条历史、LIFO 回退、失效历史清理。
- `tests/test_qt_workbench.py` 已覆盖 `Keys` 行抓手不显示 `Drag`、紧凑行距、拖拽阴影与真实行对齐、拖拽后清理选中高亮、拖拽排序保存、取消不保存、右上角关闭不保存、保存后顺序持久化。
- `tests/test_qt_workbench.py` 已覆盖大小写 Key 的按钮显示和快捷键注册，以及重复目标文件夹、仅大小写不同目标文件夹、非法保存保持弹窗打开等 `Keys` 校验行为。

## 2026-06-08 Interaction And Packaging Updates

6.5 之后又完成了一组小范围但会影响用户操作习惯和发布可靠性的更新。当前事实如下：

- Queue 搜索按钮已从文字 `Find` 调整为搜索图标按钮，保留 accessible name 和 tooltip；`Back` 保留文字并增加返回图标。
- `Keys` 弹窗会根据已有映射数量自动增高，减少用户打开后再手动拖拽窗口的需要。
- `Keys` 映射列表隐藏可见垂直滚动条，但保留鼠标滚轮滚动能力。
- 图片查看器滚轮语义已恢复为：单独滚轮切换上一张/下一张，`Ctrl+滚轮` 才缩放图片。
- Target 跟随规则已定稿：未手动选择 Target 前，切换 Source 会让 Target 跟随新 Source；用户手动选择 Target 后，本次运行期间后续切换 Source 不再覆盖 Target。这个状态只保存在当前运行会话，不新增配置 schema。
- `USER_GUIDE.md` 已补充 Queue 搜索、Back、Keys 拖拽排序、滚轮语义和 Target 跟随规则。
- `build.bat` 已加固：清理 `build/`/`dist/`、复制资源、移动 exe 或创建发布目录任一步失败都会 `exit /b 1`，避免旧 exe 被占用时误报 “Build succeeded”。
- 已重新生成发布包：`dist/ImageClassifier_Release/` 当前包含新的 `ImageClassifier.exe`、`config.json`、`USER_GUIDE.md`。

相关验证覆盖：

- `tests/test_qt_workbench.py` 已覆盖滚轮无 Ctrl 时发出导航请求、`Ctrl+滚轮` 缩放且不导航、滚轮信号驱动工作台上一张/下一张。
- `tests/test_qt_workbench.py` 已覆盖 Target 未手动选择时跟随 Source，以及手动 Target 后切换 Source 保持手动目录。
- `tests/test_qt_workbench.py` 已覆盖 `Keys` 弹窗随大量映射增高，以及映射列表隐藏垂直滚动条。
- `tests/test_packaging.py` 已覆盖打包脚本必须在发布步骤失败时退出失败。

## 2026-06-12 Classify Density Update

本次更新解决右侧分类按钮数量较多时，单列展示占用过多纵向空间的问题。当前事实如下：

- `Classify` 标题右侧为 `1`–`4` 列下拉框（`ColumnCombo`）。
- 默认保持单列，避免改变老用户的初始布局习惯。
- 选择多列后，分类按钮按当前 active profile 的映射顺序从左到右、从上到下排列。
- 切换结果会保存到 `config.json` 的 `image_classifier.classification_columns`；旧配置没有该字段时按 `1` 处理，超出 `1`–`4` 会夹到合法范围。
- 分类 key cap 继续保留原始大小写，`p` 和 `P` 不会被归一化。
- 分类按钮增加完整 Target Folder tooltip，多列压缩宽度时仍可查看完整目标目录名。
- 这只是右侧展示密度设置，不改变 `binding_profiles`、快捷键注册、文件移动、撤销或 Target 跟随规则。

相关验证覆盖：

- `tests/test_qt_workbench.py` 已覆盖默认单列展示、下拉切换多列、四列布局、越界归一化、设置持久化与重启恢复。
- `tests/test_qt_workbench.py` 已覆盖双列下大小写 key cap 仍按原始 key 展示，以及分类按钮保留完整 tooltip。

## Tech Stack

语言与运行环境：

- Python。
- 唯一指定解释器：`D:/miniforge3/envs/tool/python.exe`。
- 当前依赖见 `requirements.txt`：`Pillow>=10.0.0`、`PySide6>=6.7.0`、`pyinstaller>=6.0.0`。

桌面 UI：

- 当前主线：PySide6 / Qt。
- 旧路线：Tkinter，保留在 `main.py`、`image_classifier.py`、`shortcut_manager.py`，不是当前打包入口。

核心模块：

- `qt_main.py`：Qt 启动入口。
- `qt_workbench.py`：Qt 主窗口、工作台布局、交互流程、快捷键注册、配置保存。
- `qt_image_viewer.py`：基于 `QGraphicsView` / `QGraphicsScene` / `QGraphicsPixmapItem` 的图片加载、缩放、平移。
- `qt_theme.py`：Qt 样式表。
- `classifier_core.py`：可测试的扫描、移动、撤销、冲突命名逻辑。
- `binding_profiles.py`：按键方案迁移、规范化、兼容旧字段。
- `config_manager.py`：JSON 配置读写，兼容开发模式和 PyInstaller exe 模式。

配置与存储：

- 没有数据库。
- 没有外部服务。
- 长期配置存储在 `config.json`。
- 打包后 `config.json` 放在 exe 同目录，用户修改会长期保存。

测试与验证命令：

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -v
```

可选编译检查：

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m py_compile qt_main.py qt_workbench.py qt_image_viewer.py qt_theme.py classifier_core.py config_manager.py binding_profiles.py
```

打包命令：

```powershell
.\build.bat
```

打包脚本会清理 `build/` 和 `dist/`，运行 PyInstaller，然后创建 `dist/ImageClassifier_Release/`。如果旧发布 exe 正在运行导致 `dist` 无法删除，脚本会失败退出，不会继续误报成功。

## Constraints

环境约束：

- 使用 `D:/miniforge3/envs/tool/python.exe`，不要随意换解释器。
- 项目是 Windows 本地桌面工具，打包目标是 exe。
- 如果运行 Qt UI 测试，测试里默认设置 `QT_QPA_PLATFORM=offscreen`。

文件行为约束：

- Source 扫描是非递归扫描，只处理当前文件夹直接子文件。
- 支持格式来自 `config.json` 的 `image_classifier.supported_formats`。
- 扩展名匹配按小写归一化处理，`.JPG` 可匹配 `.jpg`。
- 图片排序使用稳定的 `sorted(Path)` 结果。
- 分类会移动文件，不会复制文件。
- 分类目录按需创建。
- 目标同名文件不能覆盖，必须生成 `stem_1.ext`、`stem_2.ext`。
- 撤销不能覆盖 Source 原位置已有文件。
- 撤销历史只保存在当前运行会话，关闭程序后丢失。
- Target 手动选择状态只保存在当前运行会话，关闭程序后恢复为未手动选择状态。

配置兼容约束：

- 按键方案位于 `config.json` 的 `image_classifier.binding_profiles`。
- 当前方案名位于 `image_classifier.active_binding_profile`。
- `image_classifier.default_key_bindings` 是兼容旧逻辑的字段，必须始终同步为当前 active profile 的映射。
- `image_classifier.classification_columns` 是右侧 `Classify` 按钮展示密度字段，接受 `1`–`4`；旧配置缺省为 `1`，超出范围会夹到合法值，不要和 binding profile 顺序混在一起处理。
- `image_classifier.move_xml_pairs` 是右侧 `LinkXML` 开关的长期配置；缺省为 `false`。切换后写入 config，下次启动恢复。
- 新建 profile 会复制当前 profile。
- 删除 profile 需要确认，默认 profile 不能删除。
- 分类 Key 目前只支持单个字符。
- 分类 Key 区分大小写；`p` 和 `P` 是两个不同 Key。不要在归一化、显示或快捷键注册时把 Key 统一转成大写。
- `Keys` 设置层会拒绝重复 Key、重复 Target Folder，以及仅大小写不同的 Target Folder。这个约束是配置阶段校验，不是 `classifier_core.py` 移动阶段的运行时猜测逻辑。

UI 与交互约束：

- Qt 工作台第一屏就是实际工具，不要做营销首页。
- `Presentation` 是隐藏复杂控件的工作台状态，不是主页。
- 分类键不应在文本框、下拉框、弹窗或文件选择对话框激活时误触。
- 移动操作必须防止快速按键导致并发移动。
- 图片加载完成后要检查 token，忽略过期加载结果。
- 图片查看器内单独滚轮用于图片导航，`Ctrl+滚轮` 才用于缩放；不要把 Queue、弹窗、列表控件的滚动事件误接到图片导航。

协作与验证约束：

- 不要删除旧 Tk 文件，除非后续明确做清理任务。
- 不要覆盖用户修改过的 `config.json`。
- 维护发布包时必须保留 `USER_GUIDE.md` 和 `config.json`。
- 声称完成前必须至少运行相关测试。涉及核心行为时跑完整 `unittest discover`。
- 修改打包逻辑时必须跑 `tests.test_packaging`。

## Completed Work

已经完成的主要工作：

- Qt 工作台已经建立，并成为 PyInstaller 打包入口。
- `classifier_core.py` 已抽出核心扫描、移动、撤销、冲突命名逻辑。
- `qt_image_viewer.py` 已使用 Qt graphics/view 实现图片查看、缩放、平移和异步加载。
- 图片加载不会显示文件名闪烁文本，切图时避免中间出现文件名占位。
- 高倍放大锐利阈值已调整到约 `1.2x fit` 以上。
- Source / Target 长路径使用中间省略显示，并通过 tooltip 保留完整路径。
- Source 选择后 Target 在未手动选择前会跟随 Source；手动选择 Target 后，本次运行期间切换 Source 不再覆盖 Target。
- 图片查看器支持单独滚轮切换上一张/下一张，并支持 `Ctrl+滚轮` 缩放。
- 按键方案支持长期保存到 `config.json`。
- `Keys` 弹窗支持 `Add Mapping` 添加更多映射行。
- `Keys` 弹窗支持拖拽调整映射顺序，保存后会同步影响分类按钮顺序、快捷键注册顺序和下次打开时的展示顺序。
- `Keys` 弹窗已支持保存前校验：非法配置会弹提示并保持弹窗打开；`Cancel` 和右上角关闭会放弃本次修改。
- 分类按钮和快捷键已支持大小写 Key 区分，右侧 key cap 会展示真实大小写。
- 右侧 `Classify` 分类按钮支持单列/双列展示切换，并会持久化用户选择。
- Queue 支持搜索图标按钮/Enter 文件名搜索，并支持输入 stem 跳转到对应图片文件。
- Queue `Back` 支持最近 5 条导航历史回退。
- 映射行内 Delete 不确认；Profile Delete 有确认。
- Recent 区域更高，操作信息放在记录最前面，并支持横向滚动。
- Presentation 展示模式已作为 Qt 工作台状态实现。
- `build.bat` 会把 `config.json` 和 `USER_GUIDE.md` 一起放入发布目录，并在清理、复制、移动或创建发布目录失败时退出失败。
- `USER_GUIDE.md` 已改成中文，并同步到 `dist/ImageClassifier_Release/USER_GUIDE.md`。

已有测试覆盖：

- `tests/test_classifier_core.py`：扫描、排序、移动、冲突命名、撤销、刷新、撤销冲突。
- `tests/test_binding_profiles.py`：旧配置迁移、当前 profile 同步到 `default_key_bindings`。
- `tests/test_qt_workbench.py`：Qt 工作台 profile 持久化、快捷键冲突优先级、大小写分类键、队列性能、Queue 搜索、5 条 Back 历史、Keys 拖拽排序、Keys 保存前校验、异步移动、跳转、滚轮导航与缩放、Keep Zoom、Target 跟随与手动保持、弹窗、Recent 等。
- `tests/test_qt_workbench.py`：右侧 Classify 按钮单列/双列切换、列数持久化、重启恢复和 tooltip 覆盖。
- `tests/test_packaging.py`：打包脚本包含配置和说明文档，spec 启动 Qt 工作台，并覆盖发布步骤失败时脚本必须失败退出。

不应随意重开的决策：

- 当前主线使用 PySide6 / Qt，不回退 Tkinter。
- 配置继续使用便携式 `config.json` 放在 exe 同目录，暂不迁移 AppData。
- 分类行为继续是移动文件，不是复制文件。
- 缩略图不是当前必须能力，文件名队列是可接受的 V1。

## Risks And No-Go Areas

最高风险区域：

- 文件移动与撤销：这是破坏性操作，任何改动都要补测试，并用临时目录验证。
- `config.json` 持久化：用户未来拿到 exe 后会依赖它保存自己的按键方案。不要在升级或打包时覆盖用户配置。
- `binding_profiles` 兼容：必须保持 `binding_profiles`、`active_binding_profile`、`default_key_bindings` 三者同步。
- 快捷键冲突：动作快捷键和分类键可能冲突，当前 Qt 逻辑保留动作快捷键优先并记录 Recent 提示。
- 大小写分类键：不要把配置、按钮展示、Recent 文本或快捷键注册中的 Key case 抹掉。`p` 和 `P` 可以共存，但 `pt` 和 `PT` 这种目标文件夹名冲突必须在 `Keys` 设置保存前拦截。
- Qt 线程：图片加载和文件移动使用 worker/thread。不要把大图解码或慢文件移动改回 UI 线程。

容易误判的文件：

- `main.py`：旧 Tkinter 启动器。当前 PyInstaller spec 不走它。
- `image_classifier.py`：旧 Tkinter 分类器。保留但不是当前 UI 主线。
- `shortcut_manager.py`：旧 Tkinter 快捷键管理器。Qt 工作台使用 `QShortcut`，不要直接以为它控制当前 UI。
- `docs/image-classifier-api.md`：偏历史和迁移设想，且内容存在编码显示问题。不能作为当前产品事实来源。
- `README.md`：存在编码显示问题和旧行为描述，优先级低于当前代码和测试。
- `docs/specs/ui-redesign.md`：是重要背景，但有部分旧行为合同已被当前代码更新。
- `dist/`、`build/`：打包产物。一般不要手工长期维护其中内容，除非用户明确要求同步发布包文件。重新打包前如果 `dist/ImageClassifier_Release/ImageClassifier.exe` 正在运行，需要先关闭它，否则清理会失败。

不要做的事：

- 不要在未确认需求时把项目改成 Web / API / Electron。
- 不要引入 AI 自动分类、训练、云同步等超出当前范围的功能。
- 不要把 Presentation 做成单独主页。
- 不要改变“移动文件”语义为“复制文件”，除非有明确新规格。
- 不要默默删除旧 Tk 文件；如果要清理，需要先确认当前发布和测试都不再引用。
- 不要使用 `git reset --hard` 或回退用户改动。

已知文档矛盾：

- `AGENTS.md` 仍说当前 app 是 Tkinter image classifier，但当前打包入口已是 `qt_main.py`。
- `docs/specs/ui-redesign.md` 的旧行为合同写 Target 默认 `source_folder.parent`，当前 Qt 代码和测试已经是 Target 未手动选择前跟随 Source。
- `README.md` 与 `docs/image-classifier-api.md` 有乱码和旧状态，不能优先采用。

## Reading Order

新人建议按这个顺序阅读：

1. `docs/PROJECT_ONBOARDING_SUMMARY.md`：当前接手摘要，也就是本文。
2. `USER_GUIDE.md`：从用户视角理解现有工具功能和实际操作流程。
3. `qt_main.py`：确认当前 Qt 启动入口。
4. `ImageClassifier.spec` 和 `build.bat`：确认当前 exe 打包路线和发布包内容。
5. `qt_workbench.py`：理解当前主窗口、Source/Target、队列、分类、profile、快捷键、Presentation。
6. `qt_image_viewer.py`：理解图片加载、缩放、平移、锐利显示和 worker 线程。
7. `classifier_core.py`：理解文件扫描、移动、冲突命名、撤销的核心业务规则。
8. `binding_profiles.py`：理解按键方案兼容和持久化规则。
9. `config_manager.py` 和 `config.json`：理解开发模式、exe 模式下配置文件位置和字段。
10. `tests/test_classifier_core.py`、`tests/test_binding_profiles.py`、`tests/test_qt_workbench.py`、`tests/test_packaging.py`：用测试确认真实行为。
11. `docs/specs/ui-redesign.md`：作为 UI 重写背景阅读，注意其中部分行为已被当前代码更新。
12. `docs/plans/2026-05-20-ui-redesign-implementation.md`：作为历史实施计划阅读，不要把未勾选项目直接当成当前事实。

暂不优先阅读：

- `main.py`、`image_classifier.py`、`shortcut_manager.py`：旧 Tkinter 路线，只有在做兼容清理或历史行为对照时再看。
- `README.md`、`docs/image-classifier-api.md`：存在旧信息或编码问题，不能作为当前事实源。
