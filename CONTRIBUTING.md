# 参与维护

先看 [项目结构与代码导航](docs/architecture.md)，按要修改的功能找到对应文件。界面、图片识别和游戏操作分开维护，不需要先读完整个项目。

## 本地开发

Windows 下使用项目自己的虚拟环境，避免系统 Python 的 Qt/DLL 与项目依赖混用：

```powershell
.\setup.bat
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

需要实机验证时再运行 `run.bat`。它会保留管理员和多开检查。单元测试不需要启动真实游戏；界面测试使用 Qt 的离屏模式和模拟引擎。

## 修改建议

后续新增功能必须延续现有分类。独立功能放 `features/<功能名>/`，按需要分离规则、识别、执行和界面；通用能力归入已有的 `desktop/`、`automation/`、`vision/` 等模块。不要为了凑目录创建空文件，也不要把新逻辑堆回主窗口或引擎协调器。目录职责变化时同步更新架构导航。仓库级约定见 [AGENTS.md](AGENTS.md)。

1. 一次提交解决一类问题。文件移动/重构与识别阈值、送键时序变化分开提交。
2. 页面排版放 `desktop/pages/`，交互放 `desktop/controllers/`；小功能独立页面可以像自动制作一样放入功能目录。
3. 通用输入控件使用 `desktop/widgets.py` 的防滚轮误改版本；字体层级和公共卡片间距复用 `desktop/design.py`，不要在各页面写独立字号。同时检查日间、夜间主题和高 DPI 缩放。
4. 新配置在 `config.py` 中添加默认值、合法性检查和旧配置兼容测试。
5. 后续功能、修复和优化均以 OK 优先：复用 OK 识别、截图及现有窗口后端，用锚点和实际客户区适配不同分辨率/DPI。默认使用 OK，旧像素模式由用户主动选择，不自动回退；新增非 OK 兼容方案先确认。不要在页面中直接模拟游戏按键。完整边界见 `AGENTS.md` 的“后续开发以 OK 优先”。
6. 对新增行为补测试，尤其是停止、画面识别失败、按键没有响应和重复触发。

`*Mixin` 目前用于保留原来的共享状态和调用方式，不是插件接口。不要给它们增加构造函数或隐式覆盖另一个分块的同名方法；新增独立功能优先分成规则、识别、执行和界面四部分。

## 验证

```powershell
# 全部回归
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 只看结构和界面组装
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_architecture.py -v

# 字体裁切、双主题和 100% / 125% / 150% / 200% 独立 Qt 缩放测试
.\.venv\Scripts\python.exe -m unittest tests.test_desktop_typography -v

# 手头有原始加工截图时，再做离线识别验证
.\.venv\Scripts\python.exe scripts/verify_crafting_references.py --source-dir "截图所在目录"
```

模板来自截图时，保留对应的生成/验证脚本，裁切掉不必要的角色名、聊天等信息。部分旧测试依赖未随仓库提供的实机素材而跳过；请在 PR 中说明测试通过、跳过以及实机验证的范围，不把离线通过等同于所有设备实测。

测试 mock 应放在被测函数实际查找依赖的位置。重构时可以修改 mock 的模块路径，但不要为了“全绿”删掉断言或跳过失败用例。`tests/test_architecture.py` 会检查旧入口、职责分块冲突、依赖方向及页面组装。

## 提交内容

PR 简单写清“改了什么、为什么、怎样验证”。涉及 UI 附日间/夜间截图；涉及识别说明截图分辨率和素材来源。不要提交本机配置、日志、诊断 ZIP、虚拟环境、`build/`、`dist/` 或 APK/EXE 成品。

`ui.py` 和根目录 `crafting_*.py` 是旧导入兼容入口，不放新业务代码。不要顺手删除其他人还在使用的入口、改版本号或启用 `remote/` 预备功能；这些应单独讨论。

需要发布时再使用 `build.bat` 打包，并验证 EXE 能实际启动。打包成功不等于 DLL 和后台操作都正常。更新说明放 Release，README 保持为使用说明。
