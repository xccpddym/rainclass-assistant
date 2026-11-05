# 开发与构建

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

真实学生端在独立 Edge 窗口中登录。账号切换、主观题策略、预算和排障详见 [使用说明](../使用说明.md)。

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

