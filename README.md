# ModelPaintPal

Windows 模型涂装配色助手：屏幕取色、模型漆匹配、可执行滴数配方与用量估算。

当前版本 **1.1.0**（2026-10-25）。

- [下载便携版和源码](https://github.com/regdiliKUN/ModelPaintPal/releases/tag/v1.1.0)
- [源码与开发说明](src/ModelPaintPal/README.md)
- [本轮优化及限制](src/ModelPaintPal/docs/OPTIMIZATION_2026-10-25.md)
- [新版完整发布目录](release/2026.10.25/ModelPaintPal-1.1.0-win-x64/)

本轮修复配方滴数与比例不同步、单色提示冲突、建议排序、跨产品线混配、用量口径、冻结包Qt依赖和热键线程生命周期。
数字色卡与混色仍是近似预测，正式涂装前请先试喷。

## 安卓版

手机端安装包在独立仓库 [**ModelPaintPal-APK**](https://github.com/regdiliKUN/ModelPaintPal-APK)，
当前 **1.4.0**：图库照片全屏取色、6× 放大预览带准星、按住即取拖动跟随。
本仓库的 `apk/` 目录不入库（见 `.gitignore`），只在本地留档。

## 开发

使用 Python 3.12。在 `src/ModelPaintPal` 下安装 `requirements-lock.txt`，然后运行：

```powershell
python run.py
python -m unittest discover -s tests
python -m pyflakes app scripts tests run.py
python scripts/build.py
```

仓库保留旧版发布目录；用户配置、历史、收藏、校准及本机备份均不入库。
