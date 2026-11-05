# RainClass 课堂 AI 助手

面向 Windows 的雨课堂学生端桌面助手。使用独立的 Microsoft Edge 会话监测正式互动题，以本地 OCR 提取题目，支持人工核对或 DeepSeek 对照原图核对，并按用户选择分析、填写和提交答案。

当前版本 **1.0.0**。已在一台 Windows 11 x64 电脑上验证；其他机器、平台改版及网络异常场景仍需自行验证。

## 功能

- 正式题目监测与新题跟随，普通 PPT 不当作互动题。
- 单选、多选、填空及文字主观题处理。
- 本地 RapidOCR / ONNX CPU 识别，模型不在运行时偷偷下载。
- 人工核对模式与 AI 原图核对模式。
- 主观题逐题授权或自动处理；可单独选择只填写、不提交。
- 新题弹窗、倒计时弹窗与主观题声音提醒，开关独立且重启记忆。
- 独立学生浏览器资料、暂停/恢复、有限刷新与设置持久化。
- 本地结果缓存、历史和用量统计；可选单课金额预算 0.1～10 元，无请求次数上限。
- 题目身份、图像、倒计时、编辑器映射与提交台账检查；提交结果未知时不自动重复提交。

AI 答案可能错误。请只在你有权使用 AI 和自动化的课堂或测试环境使用，并遵守教师、学校及平台规则。

## 下载 EXE

在 [Releases](https://github.com/xccpddym/rainclass-assistant/releases) 下载 Windows x64 ZIP，解压整个文件夹，再双击 `RainClassAssistant.exe`。

- 无需安装 Python；需要 Microsoft Edge。
- 请保留 `_internal` 文件夹，不能只复制 EXE。
- 同一专用浏览器资料不要由源码版和 EXE 同时使用。
- 关闭窗口会隐藏到托盘，真正退出请使用托盘菜单或“本地模拟 → 退出软件”。
- 文件夹内提供 HTML、TXT、Markdown 三种使用说明。

## 配置 DeepSeek

将 `config.example.toml` 复制为 `config.toml`。源码运行放在项目根目录；EXE 使用其同目录的配置。发行 ZIP 已带一份无密钥的公开配置模板。

默认模型为 `deepseek-flash`，地址为 `https://api.deepseek.com`，Key 仅从 **`DEEPSEEK_API_KEY` 环境变量**读取。不要把 Key 写进代码、提交、Issue 或截图。修改配置后重启。

首次使用默认不开启真实 AI；在“课堂设置”中选择模式并开启相关开关。自动原图核对会把当前题图与 OCR 文本发送给配置的模型，文字分析发送题目文本。金额预算按保守预留控制，并非供应商账单的硬限额；关闭金额限制也不代表免费。

## 从源码运行

环境：Windows x64、Python 3.12 或 3.13、Microsoft Edge。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item config.example.toml config.toml
powershell -File setup-ocr.ps1
python scripts/setup-models.py
$env:PYTHONPATH = 'src'
python -m rainclass --real-readonly
```

`setup-ocr.ps1` 将依赖装到项目内 `.local/ocr-runtime`；模型安装脚本从 RapidOCR 公布的源下载三个模型并校验 SHA-256。首次下载需要联网，安装后 OCR 本身离线运行。不要使用不明来源的模型文件。

真实学生端在独立 Edge 窗口中登录。账号切换、主观题策略、预算和排障详见 [使用说明](使用说明.md)。

## 测试与打包

```powershell
$env:PYTHONPATH = 'src'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests -q --basetemp .local/pytest
python -m pip install -r requirements-build.lock
powershell -File scripts/build-release.ps1 -Python python
python scripts/prepare_v1_release.py
```

产物在 `dist/v1.0.0/RainClassAssistant`。打包过程使用本机依赖和已下载的模型，不会复制个人 `config.toml`、账号资料或历史数据库。打包后应在独立数据目录执行模拟自检和离线 OCR 自检，再创建发行 ZIP。

```powershell
.\dist\v1.0.0\RainClassAssistant\RainClassAssistant.exe --smoke-test --smoke-report .local\exe-release-check\smoke.json --data-dir .local\exe-release-check\smoke-data
.\dist\v1.0.0\RainClassAssistant\RainClassAssistant.exe --ocr-self-test-report .local\exe-release-check\ocr.json
python scripts/prepare_v1_release.py --archive
```

仓库测试使用本地模拟页面和合成题目；模型接口测试使用本地假服务，不需要真实 Key。打包自检通过不等于其他设备或所有真实课堂场景通过。

## 隐私与已知限制

运行数据默认在 `%LOCALAPPDATA%/RainClassAssistant`。该目录、浏览器资料、个人配置、真实题图、诊断日志和原开发历史均未上传。详见 [隐私说明](docs/PRIVACY.md)。

- 自动模式的题图和文本会发到用户配置的 AI 服务；本地 OCR 不发送图片。
- 登录 Cookie 保存在专用 Edge 资料目录；不要把资料目录分享给别人。
- 取消预算后仍需自行关注供应商费用。
- 真实页面改版、遮挡、剩余时间不足等会停止自动作答。
- Edge 恢复/刷新偶尔可能显示到前台；锁屏、睡眠、断网情形不保证可靠。
- 主观题仅支持文字填写，不自动上传附件。
- 便携版未做代码签名，不提供安装器和自动更新。

发行包附第三方依赖许可及模型说明。此项目与雨课堂、DeepSeek 或其关联方没有官方隶属或背书关系。
