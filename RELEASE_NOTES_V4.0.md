# NCM 音乐库转换器 V4.0

V4.0 将 Windows 桌面层完整迁移到 PySide6、QML 和 Qt Quick Controls 2，同时保留原有转换核心、SQLite 数据结构、扫描规则、任务队列、设置结构和文件行为。

## 主要变化

- 使用 `QGuiApplication + QQmlApplicationEngine` 替换旧 PyQt6 Widgets 运行时。
- 新增 `ApplicationBridge`、Qt 表格模型和 PySide6 工作线程包装，继续复用现有 `LibraryDB`、扫描、转换队列、任务控制和 FLAC 服务。
- 重做音乐库、任务、历史、设置、语言分类和 FLAC → MP3 六个页面。
- 默认采用 Graphite / Teal 深色主题，并保留完整浅色主题。
- 新增 44px 自定义标题栏、196px 侧栏、Windows 原生拖动/缩放/贴靠、最大化与安全关闭流程。
- 表格支持键盘行选择、排序、筛选、勾选持久化和窄窗口横向滚动；批处理仍只使用已勾选的文件 ID。
- 使用 Lucide Outline SVG 子集和全新青绿色音乐图标，覆盖窗口、任务栏和 EXE 图标。
- 所有微动效均由真实导航、扫描、任务、进度、菜单或控件状态触发。

## 行为兼容性

- 数据库 schema 保持不变，可继续使用现有用户数据库。
- NCM 解密不转码：输出仍由文件内原始 MP3/FLAC 音频流决定。
- FLAC → MP3 独立工具仍保留原文件，并保留原有码率、输出目录、目录结构、跳过和定位行为。
- Streamlit Web 入口保持不变。
- 未增加账户、播放器、云端状态或演示用假功能。

## 验证结果

- 82 项自动化测试全部通过。
- QML 六页加载无 warning。
- 已检查 100%、125%、150%、175%、200% DPI，以及 960×640、1280×820、1600×900。
- 4,155 条记录基准通过：初始化、筛选、排序、滚动和动画页面切换均在设定门限内。
- Windows 便携包为 PyInstaller 单文件模式，并验证了源码启动、EXE 启动、ZIP 内容和 SHA-256。

## 运行环境

- Windows 10/11 x64
- Python 3.11+（仅源码运行需要）
- PySide6 6.8–6.x

如果 Windows SmartScreen 显示“未知发布者”，这是因为便携 EXE 没有商业代码签名证书。
