# 1.1.0 优化说明

日期：2026-10-25。

## 已修复

- 连续配比换算滴数后重新计算组分比例、混合颜色、ΔE与毫升量。例如15:5滴按75%:25%执行。
- 若取整后的混配没有优于单色，保留更简单的单色方案。
- 修复“单色近似（色差偏大）”与“可直接瓶用”的提示冲突，不再把数字色卡计算称为实测。
- 最终建议按实际执行配方的ΔE升序排序，再重排编号。
- 默认在同一产品线内选择调色组分，各产品线独立保留候选；用户可主动开启兼容性未验证的跨线混配。
- 原漆需求不随额外稀释比变化；旧参数按参考1:1折算为原漆基准，保留原默认1:1估算。
- 新增固定原漆损耗设置，默认0；新增预稀释产品自动模式，默认开启，可手动覆盖。
- 用量页直接展示建议引擎给出的结果，不再独立计算而漏掉遮盖力额外层数或预稀释规则。
- 用量页可滚动，较小窗口仍可访问全部参数。
- 修正SMS与星影混并的品牌信息；当前PL系列仍归SMS，未虚构新增星影色卡。
- 修正AK Real Colors为lacquer类型；现有数据库使用旧版色号与10 ml规格，没有将新18 ml产品容量套给旧版条目。
- 启动时不再自动重建桌面快捷方式；帮助菜单提供手动创建入口。
- JSON导出标注整数滴数依据、预测色差性质、容差判断和组分毫升量。
- 修复Windows冻结产物误收集Poppler同名ICU DLL导致QtCore启动失败；构建时验证系统ICU接口并排除冲突DLL。
- 修复热键监听立即停止时消息队列尚未就绪而遗留线程的问题；停止后注销窗口类，避免失效的原生回调被后续重启复用。
- GUI依赖固定为PySide6-Essentials 6.9.3，避免安装时无意升级Qt；构建依赖完整版本另存于requirements-lock.txt。

## 参数兼容

旧配置、历史、收藏及校准数据保留。新增开关缺失时采用默认值。

`mix_ml_per_m2_per_coat`保留为兼容键，其一半作为界面上的原漆单位量；110对应55 ml/m²/层。
这是明确的迁移约定，并非把汽车漆资料科学换算为模型漆的结论。新默认不新增固定损耗。

## 资料依据与限制

- SMS身份、产品漆系及直喷定位：[官方FAQ](https://www.scalemodeller.com.au/pages/faq)。
- Vallejo Model Air使用方式：[官方产品说明](https://acrylicosvallejo.com/en/category/model-air-en/)。
- AK Real Colors漆系：[官方产品线](https://ak-interactive.com/product-category/real-colors-en/)。
- RGB近似与光谱颜料模型的区别：[Practical Pigment Mixing for Digital Painting](https://scrtwpns.com/mixbox.pdf)。

默认用量系数及RGB混色仍需实喷校准。此版本修复算法口径与输出一致性，没有获得新的实漆测量数据。
“我的漆库”、按作品管理和完整试喷档案仍属于后续独立功能，不包含在本次缺陷修复中。

## 验证入口

```powershell
python -m unittest discover -s tests
python -m pyflakes app scripts tests run.py
python scripts/smoke_test.py
python scripts/check_paint_db.py
python scripts/screenshot.py
```

新增回归覆盖位于`tests/test_audit_regressions.py`和`tests/test_audit_ui.py`，对应本机肤色#D9A18C复现，以及预稀释、固定损耗、配置兼容、导出和界面一致性。
