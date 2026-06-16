# WebGoTool — 桌面网页自动化工具

> 按键精灵 + 网页自动化 + 简化版 UiPath / 影刀 RPA

**WebGoTool** 是一款桌面端网页自动化工具，通过接管用户自己的 Chrome 浏览器，实现网页元素的录制、抓取与自动回放。

---

## 功能概览

| 功能 | 说明 |
|------|------|
| 🎯 **元素抓取** | 鼠标悬停网页元素，自动识别 ID/Name/CSS/XPath |
| ⏺ **操作录制** | 自动监听 click/input/change 事件，生成可复用的流程 |
| ▶ **流程回放** | 逐条执行录制好的操作，支持变量替换 |
| 🔀 **条件判断** | if/else 分支，支持 6 种条件类型 |
| 🔄 **循环执行** | for_each / for_range / while 三种循环 |
| 📊 **数据驱动** | 读取 Excel/CSV，批量填充表单 |
| 🔍 **OCR 识别** | PaddleOCR 识别验证码，存入变量 |
| 📷 **截图** | 页面/元素截图保存 |

---

## 架构

```
┌────────────────────────────────────────────┐
│           PySide6 桌面界面 (EXE)             │
│  [录制] [停止] [运行] [保存] [抓取] [连接]    │
│  步骤列表 ─ 日志面板                         │
└──────────────────┬─────────────────────────┘
                   │ Qt Signals (线程安全)
┌──────────────────▼─────────────────────────┐
│           流程引擎 (Worker Thread)           │
│  ChromeManager → EventRecorder → WorkflowRunner │
│  Playwright CDP ← localhost:9222            │
└──────────────────┬─────────────────────────┘
                   │ CDP Protocol
┌──────────────────▼─────────────────────────┐
│              Chrome 浏览器                   │
│  DOM 操作 / 事件监听 / 页面控制              │
└────────────────────────────────────────────┘
```

## 项目结构

```
WebGoTool/
├── main.py                         # 入口
├── ui/
│   ├── mainwindow.py               # 主界面
│   └── workflow_editor.py          # 步骤编辑器
├── browser/
│   ├── chrome_manager.py           # Chrome 生命周期
│   ├── cdp_client.py               # CDP 原生命令
│   └── browser_worker.py           # 线程桥接
├── recorder/
│   └── event_recorder.py           # JS 注入录制
├── player/
│   └── workflow_runner.py          # 回放引擎
├── flows/
│   └── schema.py                   # 数据模型
├── utils/
│   ├── logger.py                   # 日志
│   └── selector_utils.py           # 选择器工具
└── resources/
    └── style.qss                   # 界面样式
```

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.10+
- Google Chrome 浏览器

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/WebGoTool.git
cd WebGoTool

# 2. 安装依赖
pip install PySide6 pandas openpyxl playwright pyinstaller

# 3. 安装 Playwright 浏览器 (可选，本工具使用系统 Chrome)
playwright install

# 4. (可选) OCR 功能
pip install paddleocr
```

### 运行

```bash
# 源码运行
python main.py

# 或打包为 EXE
pyinstaller --clean --noconfirm webgotool.spec
# EXE 在 dist/WebGoTool.exe
```

### 使用流程

1. 点击 **🔗 Connect** — 自动关闭现有 Chrome 并以调试模式重新启动
2. 点击 **🎯 Capture** — 鼠标移到网页元素上，点击确认抓取
3. 或点击 **⏺ Record** — 在 Chrome 中正常操作，自动录制
4. 点击 **⏹ Stop** 停止录制
5. 点击 **▶ Run** 回放流程
6. 点击 **💾 Save** 保存为 `workflow.json`

## Workflow JSON 示例

```json
{
  "name": "自动登录",
  "steps": [
    {
      "action": "navigate",
      "params": { "url": "https://example.com/login" }
    },
    {
      "action": "input",
      "params": { "selector": "#username", "value": "admin" }
    },
    {
      "action": "input",
      "params": { "selector": "#password", "value": "{{password}}" }
    },
    {
      "action": "click",
      "params": { "selector": "#login-btn" }
    },
    {
      "action": "wait",
      "params": { "type": "selector", "selector": ".dashboard" }
    }
  ]
}
```

### 支持的操作类型

| action | 说明 | 关键参数 |
|--------|------|----------|
| `navigate` | 打开网页 | `url`, `waitUntil` |
| `click` | 点击元素 | `selector`, `timeout`, `force` |
| `input` | 输入文本 | `selector`, `value`, `clear` |
| `wait` | 等待 | `type` (timeout/selector), `timeout` |
| `screenshot` | 截图 | `path`, `fullPage`, `selector` |
| `ocr` | 文字识别 | `selector`, `variable`, `lang` |
| `extract` | 提取数据 | `selector`, `attribute`, `variable` |
| `if` | 条件分支 | `condition`, `thenSteps`, `elseSteps` |
| `loop` | 循环 | `type` (for_each/for_range/while), `bodySteps` |
| `data_driven` | Excel 驱动 | `file`, `columnMapping`, `steps` |

### 变量系统

在 value 和 selector 中使用 `{{variable}}` 语法：

| 占位符 | 说明 |
|--------|------|
| `{{变量名}}` | 自定义变量 |
| `{{timestamp}}` | 时间戳 `20260617_103000` |
| `{{random}}` | 随机 8 位字符串 |
| `{{uuid}}` | UUID4 |
| `{{loop_index}}` | 当前循环索引 |

## 技术栈

- **UI**: PySide6 (Qt 6)
- **浏览器控制**: Playwright (CDP Protocol)
- **数据**: pandas + openpyxl
- **OCR**: PaddleOCR (可选)
- **打包**: PyInstaller

## 许可

MIT License
