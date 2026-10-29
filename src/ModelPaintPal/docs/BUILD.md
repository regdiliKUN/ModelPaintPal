# 构建与发布

## 1. 环境准备

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

- Python 3.10+（推荐 3.12 / 3.13）
- PyInstaller 6.x
- 无需安装 Qt 或 Visual Studio 生成工具

## 2. 一键构建

```bash
python scripts/build.py                  # 绿色便携版（onedir）+ zip
python scripts/build.py --mode onefile   # 单文件 exe
python scripts/build.py --no-zip         # 只出目录，不打压缩包
python scripts/build.py --no-clean      # 不清空 dist/build（增量重打包）
python scripts/build.py --clean-only     # 只清理 build/ dist/
```

脚本内部流程：
1. 用 Pillow 生成 `app/resources/icon.ico`（不依赖外部二进制资源）
2. 调用 PyInstaller，排除 40+ 个未使用的 Qt 子模块（QtQml / QtQuick / QtWebEngine /
   QtMultimedia / QtCharts …）以压缩体积
3. 把 README、LICENSE、`docs/` 拷进产物目录
4. 写入 `portable.marker`，创建 `userdata/` —— 便携版就绪
5. 打包为 `dist/ModelPaintPal-Portable.zip`

## 3. 产物

```
dist/
├── ModelPaintPal/                绿色便携版目录（整目录拷贝即可用）
│   ├── ModelPaintPal.exe
│   ├── _internal/                运行时（Qt / Python / 依赖）
│   ├── docs/                     文档
│   ├── README.md  LICENSE
│   ├── portable.marker           存在时用户数据写在同级 userdata\
│   └── userdata/                 配置 / 历史 / 收藏 / 校准 / 日志
├── ModelPaintPal-Portable.zip    ≈ 54 MB
└── ModelPaintPal.exe             单文件版（--mode onefile）
```

## 4. 便携模式 vs 安装模式

| | 便携模式 | 安装模式 |
| --- | --- | --- |
| 触发条件 | exe 同级存在 `portable.marker` | 不存在 |
| 数据位置 | `<exe目录>\userdata\` | `%APPDATA%\ModelPaintPal\` |
| 适用场景 | U 盘携带、多机共用 | 单机固定使用 |

切换方式：删/建 `portable.marker` 即可。

## 5. 生成安装包（可选）

仓库附带 `installer.iss`（Inno Setup 脚本）。需要本机安装
[Inno Setup 6](https://jrsoftware.org/isinfo.php)：

```bash
ISCC.exe installer.iss
```

产物：`dist\Installer\ModelPaintPal-Setup-1.2.0.exe`（版本号取自 `installer.iss` 的
`MyAppVersion`，须与 `app/__init__.py` 的 `__version__` 一致），支持：
- 中英文安装界面、开始菜单快捷方式、桌面图标
- 安装后自动写入 `%APPDATA%`（不含 `portable.marker`，即安装模式）
- 卸载清理

若不想装 Inno Setup，直接分发便携版 zip 即可。

## 6. 常见问题

**Q：构建时报找不到 PyInstaller？**
```bash
pip install pyinstaller
```

**Q：运行时报缺 DLL / Qt platform plugin？**
多半是误删了排除列表里的模块。先检查是否排除了 `PySide6.QtSvg`（本应用用于图标渲染），
必要时从 `scripts/build.py` 的 `EXCLUDED_MODULES` 中移除相关项后重新构建。

**Q：杀毒软件误报？**
PyInstaller 打包产物是常见的误报来源。可用 `--mode onefile` 之外的 onedir 形式，
或在 Inno Setup 里做代码签名（需自备证书）。

**Q：热键没反应？**
- 检查设置页的热键是否被其它软件占用（占用时状态栏会提示）
- 某些受保护窗口（如以管理员运行的程序）会吞掉热键，此时用界面按钮吸色即可

**Q：吸色位置偏了？**
确认系统缩放不是非整数倍以外的异常值；若仍偏移，在设置里把「取样区域」调大，
用中心平均（3×3 / 5×5）抵消亚像素误差。

## 7. 构建前自检（推荐）

```bash
python -m pyflakes app scripts tests run.py
python -m unittest discover -s tests
python scripts/smoke_test.py
python scripts/check_paint_db.py
python scripts/check_regression.py    # 配方结果指纹：确认「算出来的还是同一个东西」
python scripts/bench.py               # 性能锚点（性能优化前后必跑）
python scripts/build.py
```

`check_regression.py` 与 `bench.py` 是一对：前者保证**结果不变**，后者保证**速度变快**。
只跑其中一个都会得出错误结论——「快了但配方换了」和「结果一样但慢了」都不算优化。
