# 纯ai生成代码

# AI only，chinese only。If anyone needs other languages, please let me know.

# EU4 联机自动存档与分析助手

面向 Europa Universalis IV `1.37.5.0 / 491d` 的 Windows 客机自动存档、归档和存档分析工具。当前源码版本为 `1.2.0`。

本仓库是可独立构建的维护源码，不包含用户存档、配置、运行日志、数据库、游戏美术资源、地图缓存、预编译原生模块或下载后的工具链。发行版由仓库内 Python 与 C++ 源码重新构建。

> 原生桥会向正在运行的 `eu4.exe` 注入 DLL，并在游戏主线程调用客机本地保存入口。默认只允许构建标识 `491d`。即使版本与特征校验通过，仍可能发生游戏崩溃、联机掉线或存档失败；使用前请备份存档并先在受控环境测试。非 `491d` 风险模式不代表兼容性保证。

## 主要功能

- 联机客机手动存档，以及按游戏季度、游戏年度或现实时间定时存档。
- 对桥接生成的文件执行稳定性等待、完整解析、SHA-256 校验、归档改名和撤销。
- 可选归档保留策略：清理超过 90 天的存档，并在剩余文件中保留最新 500 份；重要战局应另行备份。
- 读取明文 `EU4txt`、普通 ZIP 和 `EU4bin` 铁人 ZIP；铁人内容通过本机 Rakaly CLI 解码，不上传或改写原存档。
- 可拖动、缩放的政治地图、省份所有权与控制权叠加、军队位置和兵力标记。
- 原版及单个 Mod 资源覆盖；缺失的 Mod 文件自动回退到用户本地原版游戏目录。
- 中文国名、国家经济与点数分析、玩家经济告警、多存档对比和贷款容量估算。
- 半透明置顶小窗口、多人玩家国家切换、鼠标穿透锁定和可配置的全局快捷键。
- 可轮转运行日志、Python 崩溃报告和原生故障日志。

## 仓库结构

```text
src/eu4_assistant/   Python 应用源码
native/              DLL、注入器、启动器和仿真测试程序源码
tests/               Python 自动化测试
scripts/             环境安装、依赖获取、测试、地图缓存与发行构建脚本
tools/               原生桥与 491d 分析辅助脚本
data/                可再分发的中文国名数据
licenses/            随发行包使用的第三方许可证文本
.github/workflows/   GitHub Actions 测试和构建工作流
```

`LIVE_TEST_CHECKLIST.md` 记录仍需真实联机客机环境完成的低风险验收项目。自动化测试和仿真测试不能替代真实游戏验收。

## 开发环境

要求：

- Windows 10/11 x64
- Python 3.11 或更高版本
- PowerShell 5.1 或 PowerShell 7
- 构建原生模块或发行包时需要网络下载固定版本 Zig 0.13.0
- 构建包含铁人存档支持的发行包时需要下载固定版本 Rakaly CLI 0.8.19

首次安装：

```powershell
Set-Location path\to\EU4_AutoSave_Assistant
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

`setup.ps1` 会在仓库内创建被 Git 忽略的 `.venv`。游戏目录优先读取 `EU4_GAME_DIR`，否则尝试通过 Steam 注册表和常见安装目录自动探测；源码不包含开发者电脑的固定路径。

运行测试：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

运行源码程序：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_app.ps1
```

若需要从源码直接解析 `EU4bin` 铁人存档，先获取 Rakaly：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\get_rakaly.ps1
```

脚本从 Rakaly 官方 GitHub Release 下载 Windows x64 ZIP，并同时校验固定的发行包和可执行文件 SHA-256。文件写入被 Git 忽略的 `.tools`。

## 原生桥构建与测试

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_native.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_native_bridge.ps1
```

构建脚本从 Zig 官方站点下载 `zig-windows-x86_64-0.13.0.zip`，验证固定 SHA-256 后解压到 `.tools`。编译生成物写入 `build`，不会提交到 Git。

`tools/analyze_491d.py` 可对用户自行提供的 `eu4.exe` 检查已知 491d 特征与入口前导字节；仓库不包含游戏可执行文件或其反汇编产物。

## 可选地图缓存

仓库不分发由 EU4 游戏文件生成的省份栅格和国家颜色缓存。缺失时程序会从用户自己的游戏安装目录生成。

发布前可预生成缓存以改善首次启动速度：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare_map_data.ps1 `
  -GameDirectory 'C:\Program Files (x86)\Steam\steamapps\common\Europa Universalis IV'
```

生成内容位于 `data\province_index.json` 和 `data\map_cache`，已被 `.gitignore` 排除，但打包脚本会在它们存在时收入发行包。缓存内容可能源自本地游戏文件，公开发布前应单独确认再分发权限。

## 构建发行包

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\package.ps1
```

该命令会：

1. 从 `native` 源码编译 DLL、注入器和顶层启动器。
2. 下载并校验固定版本 Rakaly CLI。
3. 用仓库内 `.venv` 执行 PyInstaller，并裁剪未使用的 Qt 模块和插件。
4. 运行离屏发行版冒烟测试。
5. 清除日志、配置、数据库和归档等运行痕迹。
6. 在 `dist` 生成 `EU4_AutoSave_Assistant_Final_491d_1.2` 目录和同名 ZIP。

可指定发行版本：

```powershell
.\scripts\package.ps1 -ReleaseVersion '1.2.1'
```

## 公开仓库边界

`.gitignore` 排除以下内容：

- `.venv`、`.tools`、Python 缓存和包元数据。
- `build`、`dist`、`release`、EXE/DLL/ZIP 等生成物。
- `config`、`logs`、`archives`、SQLite 数据库和 `*.eu4` 存档。
- 从本地游戏生成的 `province_index.json` 与 `map_cache`。

发布源码前仍应检查 `git status` 和 `git diff --cached`。提交故障报告时只提供经过脱敏的最小日志片段；日志可能包含本机路径、玩家名和存档文件名。

## GitHub 发布建议

- 源码提交到 Git 仓库。
- `dist/*.zip` 作为 GitHub Release 附件上传，不要提交进源码历史。
- 公开前先决定项目许可证；当前仓库未向项目源码授予开源许可。
- 不要在源码、发行包或更新器中嵌入私有仓库令牌。

## 许可说明

本项目源码当前没有开源许可证，因此默认保留全部权利。中文国家名称数据与 Rakaly CLI 的来源和许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。Europa Universalis IV、相关商标以及游戏资源属于 Paradox Interactive；本项目不包含原版游戏图像或游戏可执行文件。
