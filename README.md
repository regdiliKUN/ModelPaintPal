# ModelPaintPal

Windows 模型涂装配色助手：屏幕取色、模型漆匹配、可执行滴数配方与用量估算。

当前版本 **1.2.0**（2026-10-30 发布）。

- [下载便携版和源码](https://github.com/regdiliKUN/ModelPaintPal/releases)
- [源码与开发说明](src/ModelPaintPal/README.md)
- [迭代记录（43 轮）](src/ModelPaintPal/docs/ITERATION_2026-10-29.md)
- [性能优化说明](src/ModelPaintPal/docs/OPTIMIZATION_2026-10-29.md)
- [1.1.0 更新说明](src/ModelPaintPal/docs/OPTIMIZATION_2026-10-25.md)
- [1.2.0 完整发布目录](release/2026.10.30/ModelPaintPal-1.2.0-win-x64/)
- [1.1.0 发布目录](release/2026.10.25/ModelPaintPal-1.1.0-win-x64/)
- [安卓版（源码与安装包，独立仓库）](https://github.com/regdiliKUN/ModelPaintPal-APK)

本轮把配色搜索提速 **9.7×**（配方结果逐位不变）、补上此前没有界面入口的「配色方案」
页（互补 / 三角 / 邻近 / 单色系等 7 种）、连续吸色时排队中的陈旧计算直接放弃，并修掉
一批边界与一致性问题。数字色卡与混色仍是近似预测，正式涂装前请先试喷。

## 开发

使用 Python 3.12。在 `src/ModelPaintPal` 下安装 `requirements-lock.txt`，然后运行：

```powershell
python run.py
python -m unittest discover -s tests
python -m pyflakes app scripts tests run.py
python scripts/build.py
```

仓库保留旧版发布目录；用户配置、历史、收藏、校准及本机备份均不入库。
