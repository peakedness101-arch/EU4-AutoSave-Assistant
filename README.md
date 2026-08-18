# EU4 联机自动存档与分析助手

面向 Europa Universalis IV `1.37.5.0 / 491d` 的 Windows 客机自动存档、归档和存档分析工具。

本仓库是可独立构建的维护源码，不包含用户存档、运行日志、配置数据库、游戏美术资源或预编译工具链。发行版从仓库内 Python 与 C++ 源码重新构建，不依赖旧发行目录。

> 原生桥会向正在运行的 `eu4.exe` 注入 DLL。默认只允许构建标识 `491d`，但注入仍具有游戏崩溃、联机掉线和存档失败风险。请先备份存档并在受控环境测试。

## 主要功能

- 联机客机手动与定时自动存档。
- 存档批量改名、归档、校验和撤销。
- 可拖动、缩放的政治地图和省份驻军提示。
- 中文国名、国家经济与点数分析、玩家经济告警。
- 多存档数据变化对比和贷款容量估算。
- 可轮转运行日志、Python 崩溃报告和原生故障日志。

## 仓库结构

```text
src/eu4_assistant/   Python 应用源码
native/              DLL、注入器、启动器和仿真测试程序源码
tests/               Python 自动化测试
scripts/             环境安装、测试、地图缓存与发行构建脚本
tools/               原生桥测试辅助脚本
data/                可再分发的中文国名数据
.github/workflows/   GitHub Actions 测试和构建工作流
```

## 开发环境

要求：

- Windows 10/11 x64
- Python 3.11 或更高版本
- PowerShell 5.1 或 PowerShell 7
- 构建原生模块或发行包时需要网络下载固定版本 Zig 0.13.0

首次安装：

```powershell
Set-Location path\to\EU4_AutoSave_Assistant
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

`setup.ps1` 会在仓库内创建被 Git 忽略的 `.venv`，不依赖开发者电脑上的固定 Python 路径。

运行测试：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

运行源码程序：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_app.ps1
```

## 原生桥构建与测试

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_native.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_native_bridge.ps1
```

脚本会从 Zig 官方站点下载 `zig-windows-x86_64-0.13.0.zip`，验证固定 SHA-256 后解压到被忽略的 `.tools`。编译生成物写入 `build`，不会提交到 Git。

## 可选地图缓存

仓库不分发由 EU4 游戏文件生成的省份栅格和国家颜色缓存。它们不是构建程序所必需；缺失时程序会从用户自己的游戏安装目录生成。

发布前可预生成以改善首次启动速度：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare_map_data.ps1 `
  -GameDirectory 'C:\Program Files (x86)\Steam\steamapps\common\Europa Universalis IV'
```

生成内容位于 `data\province_index.json` 和 `data\map_cache`，已被 `.gitignore` 排除，但打包脚本会在它们存在时自动收入发行包。

## 构建发行包

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\package.ps1
```

该命令会：

1. 从 `native` 源码编译 DLL、注入器和顶层启动器。
2. 用仓库内 `.venv` 执行 PyInstaller。
3. 裁剪未使用的 Qt 模块和插件。
4. 运行离屏发行版冒烟测试。
5. 清除日志、配置、数据库和归档等运行痕迹。
6. 在 `dist` 生成 `EU4_AutoSave_Assistant_Final_491d_1.1` 目录和同名 ZIP。

可指定发行版本：

```powershell
.\scripts\package.ps1 -ReleaseVersion '1.2'
```

## GitHub 发布建议

- 源码提交到 Git 仓库。
- `dist/*.zip` 作为 GitHub Release 附件上传，不要提交进源码历史。
- 仓库公开前先决定许可证；当前仓库未授予开源许可。
- 保持仓库私有时，只邀请被授权的维护者和用户。

## 数据与隐私

不要将以下内容提交到问题报告或仓库：

- `.eu4` 存档，除非已确认可以公开其中的玩家信息。
- `config`、`archives` 和 SQLite 数据库。
- 未检查的完整日志；日志可能包含本机路径和存档文件名。

提交故障报告时，优先提供最小化且已脱敏的日志片段。

## 许可说明

本仓库当前没有开源许可证，因此默认保留全部权利。中文国家名称数据的来源和许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。Europa Universalis IV 及其商标和游戏资源属于 Paradox Interactive；本项目不包含原版游戏图像。

