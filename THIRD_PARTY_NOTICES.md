# Third-party notices

## EU4 中文百科国家列表

`data/country_names.html` 是用户提供的“国家”页面离线快照，用于 TAG 到中文国家名称的本地映射。页面自身声明采用 [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-nc-sa/4.0/) 许可。

- 页面标题：国家 - 欧陆风云4百科
- 来源站点：[www.eu4cn.com](https://www.eu4cn.com/)
- 原页面规范名称：`国家.html#国家代码列表`
- 快照日期：2024-06-18
- 本项目对其用途：离线解析国家 TAG 与中文名称；未修改页面正文

该数据的再利用必须遵守署名、非商业和相同方式共享条款。程序源码的许可状态不会覆盖该第三方内容。

## Rakaly CLI

发行构建使用 [Rakaly CLI v0.8.19](https://github.com/rakaly/cli/releases/tag/v0.8.19) 在用户本机解码 Paradox `EU4bin` 存档。仓库不提交 Rakaly 可执行文件；`scripts/get_rakaly.ps1` 从官方 GitHub Release 下载 Windows x64 发行包，并校验固定 SHA-256。

Rakaly CLI 采用 MIT License。许可证全文保存在 `licenses/Rakaly.txt`，打包时会随 `rakaly.exe` 一起复制到发行目录。

## Europa Universalis IV

Europa Universalis IV、相关商标以及游戏内图像和数据归 Paradox Interactive 所有。本仓库不包含原版游戏图像；运行时仅从用户本地安装目录读取界面图标和旗帜。
