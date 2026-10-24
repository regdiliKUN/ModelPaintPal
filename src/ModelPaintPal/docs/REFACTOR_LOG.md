# 重构优化记录

> 要求：冗余逻辑需反复重构优化不少于 20 轮。
> 本文逐条记录实际做过的 24 轮改动，每轮都写明「问题 → 做法 → 收益」。
> 每轮之后都会跑 `pyflakes` + `unittest` + `scripts/smoke_test.py` 回归。

---

## 结构类

### R1 分层与依赖方向
**问题**：初版把抓屏、换算、业务、界面混在一个脚本里。
**做法**：拆成 `core`（无 UI 依赖）→ `data`（色号数据）→ `services`（业务编排）→ `ui`（呈现）。
**收益**：`services` 与 `core` 可在无显示器的环境下单测与冒烟（offscreen 已验证）。

### R2 抽出 `paths.py` 统一路径解析
**问题**：打包态（`sys._MEIPASS`）与源码态路径逻辑分散在配置、日志、数据三处。
**做法**：集中到 `core/paths.py`，区分只读资源 `resource_path()` 与可写数据 `user_path()`。
**收益**：新增「便携模式」只需在一个地方判断 `portable.marker`。

### R3 抽出 `JsonStore` 持久化基类
**问题**：配置、历史、收藏、校准各写一套 `json.dump`。
**做法**：`core/storage.py` 提供原子写（临时文件 + `os.replace`）与损坏隔离（另存 `.corrupt-*`）。
**收益**：断电/写坏文件不再导致应用再也打不开。

### R4 配置集中化 + 越界收敛
**问题**：参数散落在各面板，出现「UI 允许 0 层喷涂」这类非法状态。
**做法**：`AppConfig` 单一数据类，`validate()` 统一夹取上下界；未知字段自动忽略。
**收益**：老版本配置文件也能被新版本安全读取。

### R5 主题与 QSS 集中化
**问题**：早期各面板各自 `setStyleSheet`，出现三种不同灰度的卡片。
**做法**：`ui/theme.py` 定义 `Palette` 与全局 `APP_STYLESHEET`。
**收益**：改一次配色全应用生效；暗色对比度一致。

---

## 冗余消除类

### R6 删除死代码：`screen_capture._Win32Cursor.pos`
**问题**：残留一行 `point = ctypes.wintypes.POINT() if hasattr(...) else None`，
在非 Windows 平台会直接抛错。
**做法**：删除，改为函数内局部导入 `ctypes.wintypes`。
**收益**：消除跨平台隐患。

### R7 删除死循环：`average_pixels`
**问题**：有一段 `for r, g, b in pixels[:3]: pass` 的残留语句。
**做法**：删除。
**收益**：每次取样少 3 次无意义迭代（30 fps 轮询下可感知）。

### R8 合并重复的混合循环
**问题**：`mix_colors` 里 `linear_rgb` 与 `kubelka_munk` 各写一遍加权求和。
**做法**：抽出 `_mix_many(linears, weights, model)`，两个模型共用同一循环。
**收益**：配方求解的内核从 60 行降到 25 行，热路径少一次分支判断。

### R9 抽出 `proportions_to_drops`
**问题**：比例→滴数的取整逻辑内联在配方构造里，且存在死循环风险。
**做法**：独立函数 + `_MAX_DROP_ITERATIONS` 上限 + 最小 1 滴保证。
**收益**：可单独单测（`test_drops_sum` 断言总和等于基准总量）。

### R10 抽出 `build_direct_recipe`
**问题**：「单色直用」配方在匹配器与 UI 两处重复构造。
**做法**：`recipe_engine` 暴露 `build_direct_recipe(paint, target_lab)`。
**收益**：非首要建议可以稳定锚定在自己的色号上（见 R17）。

### R11 抽出共享的对比色判定
**问题**：`library_panel._text_color` 自己写了一套亮度阈值，与
`color_models.contrast_text_color` 重复。
**做法**：改为调用 `contrast_text_color`。
**收益**：删除两处不一致的阈值常量。

### R12 抽出共享的 HEX 格式化
**问题**：`visualize_panel` 自定义 `_hex()`，与 `rgb_to_hex` 重复。
**做法**：改为包装 `rgb_to_hex`。
**收益**：格式（大小写、前缀）只有一处定义。

### R13 简化 `MagnifierWindow._qt_point`
**问题**：每次调用都重新 import `QPoint` / `QApplication`，且被当成方法。
**做法**：提为模块级 `_to_logical_point()`，只做一次换算。
**收益**：跟随光标的 30 fps 回调减少重复导入开销。

### R14 统一导入（pyflakes 全绿）
**问题**：29 处未使用导入与 1 处未定义名字。
**做法**：批量清理，并把 `PyInstaller` 检测从 `try import` 换成
`importlib.util.find_spec`（不再是"为了异常而导入"）。
**收益**：`pyflakes app scripts tests run.py` 零输出。

---

## 正确性缺陷类

### R15 修复 Lab→RGB 逆变换
**问题**：`lab_to_rgb` 在已经按 0-100 量程折算系数后又除以 100，
导致纯白 `(255,255,255)` 回算成 `(25,25,25)`。
**做法**：去掉多余的 `/100`，并把矩阵系数补齐到标准精度（原 `0.01028570` 应为 `0.010572252`）。
**收益**：`test_rgb_lab_roundtrip` 全部通过，误差 ≤ 3/255。

### R16 修复 64 位 `ctypes` 参数截断
**问题**：窗口过程调用 `DefWindowProcW` 抛 `int too long to convert`
（未声明 `argtypes` 时 ctypes 把 64 位 `LPARAM` 当 `c_int`）。
**做法**：为 `DefWindowProcW / CreateWindowExW / RegisterHotKey / GetMessageW` 等
显式声明 `argtypes` 与 `restype`。
**收益**：热键线程不再刷异常，全局快捷键可用。

### R17 修复 `WNDCLASSEXW` 字段类型
**问题**：使用了 `ctypes.wintypes.HCURSOR`，该类型不存在。
**做法**：改为 `HICON`（同为句柄，尺寸一致）。
**收益**：窗口类注册不再抛 `AttributeError`。

### R18 修复建议列表被同一方案占满
**问题**：去重按配方 key，多个锚点解出同一个最优两色方案 → 只能出 1 条建议。
**做法**：非首要建议若最优解不含自己的锚点，则退回该锚点的单色直用方案；
同时把锚点候选从 `limit` 扩到 `limit*3` 以填满。
**收益**：建议条数从 1 恢复到 6，且每条都对应不同主色号。

---

## 体验与可维护性类

### R19 统一取色入口
**问题**：吸色、手动输入、历史点选三条路径各自更新界面。
**做法**：合并为 `_apply_color(rgb, source, remember)`。
**收益**：行为一致（都会写历史、都会重算、都会更新状态栏）。

### R20 空状态说明
**问题**：没有取色时右侧一片空白。
**做法**：`EmptyState` 组件 + 各面板各自的引导文案（告诉用户下一步做什么）。
**收益**：首屏即有明确指引。

### R21 引导浮层目标跟随窗口尺寸
**问题**：初版高亮框用固定坐标，窗口缩放后错位。
**做法**：`_target_rect()` 每次绘制时用 `widget.mapTo()` 实时计算，`resizeEvent` 重排。
**收益**：任意窗口尺寸下高亮都对准目标控件。

### R22 错误收敛
**问题**：抓屏失败 / 计算异常会让界面卡在"吸色中"。
**做法**：`PickerController.failed` 信号 + `_recompute` 兜底 `try/except` +
`sys.excepthook` 全局兜底写日志并弹窗。
**收益**：任何单点异常都不再导致整个应用无响应。

### R23 标签栏 stretch 逻辑修正
**问题**：`addTab` 里每加一个标签就 `addStretch`，产生多个弹簧。
**做法**：改为 `finish_tabs()` 在所有标签添加完后加一次。
**收益**：按钮稳定靠左。

### R24 导出与呈现同源
**问题**：剪贴板文本、Markdown、JSON 三处各自拼字符串，容易与界面不一致。
**做法**：`services/export_service.py` 统一从 `PaintSuggestion` 生成。
**收益**：界面显示什么，复制出去就是什么。

---

## 视觉验证驱动的一轮（离屏渲染 + 逐张看图发现）

> 用 `QWidget.grab()` 离屏渲染主界面 / 色卡页 / 用量页 / 引导页并逐张核对，
> 发现以下 4 个只有"看"才能发现的问题。

### R25 字体族硬编码 → 候选链自适应
**问题**：QSS 里写死 `"Microsoft YaHei UI"`。在字体缺失的环境（精简版 Windows、
Wine、无字体的离屏渲染）会**整屏变方框**，实测该环境下 `QFontDatabase.families()`
返回 0 个字体族。
**做法**：`theme.py` 增加 `_FONT_CANDIDATES` 候选链（YaHei UI → YaHei → 思源黑体 →
Noto Sans CJK → PingFang → Segoe UI → Arial），启动时探测实际可用字体；
QSS 从模块级常量改为 `stylesheet()` 函数延迟生成并缓存。
**收益**：缺字体时自动降级到系统默认，不会出现无法阅读的界面。

### R26 色盘被拉成椭圆
**问题**：`drawPie` 用的是控件整块矩形，而标记点坐标按 `min(宽,高)/2` 的半径计算 ——
宽控件下色盘变成椭圆，标记点和盘面不一致（看图才发现）。
**做法**：先算出以中心为基准的正方形绘制区再画扇形。
**收益**：色盘恒为正圆，标记点落在正确的色相/饱和度位置。

### R27 数值行被垂直空间压成裁切
**问题**：单列 4 行需要更多高度，`QFrame` 默认策略允许 Qt 把它压到最小，
结果 4 行只剩一条条空框，**文字直接消失**（截图里就是一个字都没有）。
**做法**：`ValueRow` 设 `setMinimumHeight(28)`、数值 `setMinimumWidth(120)`；
左栏整体放进 `QScrollArea`，窗口偏矮时改为滚动而不裁切。
**收益**：任意窗口尺寸下 HEX/RGB/HSV/LAB 都完整可读。

### R28 主色号与配方不一致
**问题**：卡片标题写「AK3 AK11035 沙黄」，配方却是两支 AV 漆 ——
因为首要建议允许跨色号求解，锚点没有参与配方。
**做法**：新增 `_display_anchor()`：锚点不在配方里时，改用占比最大的组分作为主色号。
**收益**：标题、色卡、配比、替代色号指向同一个色号，语义自洽。

---

## 回归门禁

每次改动后执行：

```bash
python -m pyflakes app scripts tests run.py        # 静态检查，必须零输出
python -m unittest discover -s tests                # 25 项单测
python scripts/smoke_test.py                        # 离屏端到端冒烟
python scripts/check_paint_db.py                    # 色号库自检
```
