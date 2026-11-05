# 开发与构建

面向想从源码运行、调试或自行打包的人。终端用户请看[使用说明](../使用说明.md)。

## 环境

| 项目 | 版本 |
| :--- | :--- |
| Windows | x64（本机为 Windows 11） |
| Python | 3.12 ~ 3.13（`requires-python = ">=3.12,<3.14"`） |
| 浏览器 | Microsoft Edge |
| 运行时依赖 | `PySide6==6.11.2`、`playwright==1.62.0` |
| 测试依赖 | `pytest==9.2.0` |
| OCR 依赖 | `rapidocr==3.10.0`、`onnxruntime==1.31.1`、`opencv-python-headless==4.10.0.84` |

精确版本分别锁在 `requirements.lock`、`requirements-build.lock`、`requirements-ocr.lock`。

## 从源码运行

```powershell
git clone https://github.com/xccpddym/rainclass-assistant.git
cd rainclass-assistant

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"

Copy-Item config.example.toml config.toml
powershell -File setup-ocr.ps1          # 安装 OCR 依赖到项目内 .local/ocr-runtime
python scripts/setup-models.py          # 下载并校验 OCR 模型

$env:PYTHONPATH = 'src'
python -m rainclass --real-readonly
```

也可以 `python -m rainclass`（只开本地模拟页），或安装后使用入口点 `rainclass`。

### OCR 模型

`scripts/setup-models.py` 从 RapidOCR 公布的来源下载三个模型，逐个校验 SHA-256，通过后才落盘。首次下载需要联网，之后 OCR 全程离线。

不要使用来源不明的模型文件，也不要跳过哈希校验——OCR 是整条链路里唯一处理真实题图又不联网的环节。

## 命令行参数

| 参数 | 作用 |
| :--- | :--- |
| `--real-readonly` | 打开真实课堂页签（核对、分析、可选自动作答） |
| `--data-dir <路径>` | 指定独立数据目录，隔离测试，不继承当前账号与设置 |
| `--smoke-test` + `--smoke-report <文件>` | 本地模拟作答自检，输出 JSON 报告 |
| `--ocr-self-test-report <文件>` | 离线 OCR 自检，输出 JSON 报告 |

## 项目结构

```
src/rainclass/
  app.py                 主窗口、页签、托盘、命令行入口
  real_panel.py          真实课堂页与课堂设置页
  real_worker.py         真实课堂后台工作线程
  real_analysis.py       原图 + OCR → AI 核对与解题
  real_answer.py         答案填写与提交
  real_review.py         题目核对交互

  browser.py             Edge 启动、页面与 DOM 操作
  discovery.py           课堂发现
  direct_discovery.py    直接进入课程
  follow.py              新题跟随
  presentation.py        PPT 与正式互动题的区分
  live.py                真实学生端会话

  ocr.py                 OCR 运行时与模型加载
  question_ocr.py        题目区域切分与文本结构化
  history.py             历史回顾提取

  ai.py                  AI 客户端（含离线 FakeAI）
  storage.py             SQLite 缓存、历史与防重记录
  timing.py              倒计时与提醒阈值
  focus_guard.py         焦点保持
  notification_popup.py  新题与倒计时弹窗
  blank_panel.py         填空面板
  auto_review.py         自动核对流程编排
  analysis_errors.py     失败分类与转人工判定

  mock.py                本地模拟课堂
  core.py                模拟课堂核心逻辑
  diagnostics.py         只读结构诊断
  smoke.py / ocr_smoke.py 自检入口
```

`tests/` 覆盖上述模块，`tests/fixtures/` 保留三张不含身份信息的题目测试图。

## 测试

```powershell
$env:PYTHONPATH = 'src'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests -q --basetemp .local/pytest
```

- Qt 用例需要 `QT_QPA_PLATFORM=offscreen`，否则在无桌面环境会挂起。
- `--basetemp` 指向 `.local/pytest`，避免测试父目录不存在时启动失败。
- 模型接口测试走本地假服务，**不需要真实 Key**，也不产生费用。
- 真实课堂相关用例使用静态 fixture 与本地模拟页，不访问真实平台。

本机全量回归约 385 个用例、4~5 分钟。

## 打包

```powershell
python -m pip install -r requirements-build.lock
powershell -File scripts/build-release.ps1 -Python python
python scripts/prepare_v1_release.py            # 生成发行目录
python scripts/prepare_v1_release.py --archive  # 生成 ZIP 与 SHA-256 校验文件
```

产物在 `dist/v1.0.0/RainClassAssistant`。打包只使用本机依赖与已下载模型，**不会**复制个人 `config.toml`、账号资料或历史数据库。

### 打包后必须先自检

```powershell
.\dist\v1.0.0\RainClassAssistant\RainClassAssistant.exe `
  --smoke-test --smoke-report .local\exe-release-check\smoke.json `
  --data-dir .local\exe-release-check\smoke-data

.\dist\v1.0.0\RainClassAssistant\RainClassAssistant.exe `
  --ocr-self-test-report .local\exe-release-check\ocr.json
```

两项都通过后再生成 ZIP。自检通过只说明冻结后的 EXE 能跑通本地模拟与离线 OCR，**不代表**其他设备或真实课堂场景可用。

`scripts/verify_release.ps1` 可对发行包做结构与哈希复核。

## 发布流程

仓库以**脱敏源码快照**形式公开：不含个人 `config.toml`、`.env`、Key、Cookie、浏览器资料、数据库、真实课堂图片与文档、内部交接与原始报告。

维护时请遵守：

- **不要**对本地开发仓库执行 `push --all` / `--mirror`，也不要推送旧标签——原开发历史含个人信息。
- 更新方式：从远端拉取干净仓库 → 选择性同步已审查的源码 → 提交 → 推送。
- EXE 只通过 Releases 分发，不进入 Git 历史。
- 提交前检查：新增文件是否含绝对路径、个人邮箱、Key 或令牌特征、课堂链接与课程标识。
- `.local/`、`*.sqlite3`、`dist/`、`build/`、`release/` 已在 `.gitignore` 中排除。

## 常见开发问题

**Qt 窗口在测试里挂起**
确认 `QT_QPA_PLATFORM=offscreen`，并检查没有残留 Edge 进程占用专用资料目录。

**OCR 模型校验失败**
重新执行 `python scripts/setup-models.py`。校验失败通常是下载不完整或文件被替换，确认来源后再重试，不要跳过校验。

**测试启动即失败**
用 `--basetemp .local/pytest` 指定测试临时目录，并确认 `.local/` 存在且可写。

**Edge 被占用**
同一个专用资料目录只能被一个进程使用，先确认旧的 `RainClassAssistant.exe` 已完全退出。
