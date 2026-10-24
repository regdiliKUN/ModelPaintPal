# ModelPaintPal 第三轮持续优化 · 迭代记录

> 对象：3D 打印模型涂装配色助手（`ModelPaintPal`）
> 范围：**不改动核心需求与分层结构**，只在 `ui` / `services` / `core` 内部做实质性优化
> 门禁：每轮之后跑 `pyflakes`（零输出）+ `unittest`（全绿）+ `scripts/smoke_test.py`（全 PASS）
> 记录方式：每轮写明「目标 → 改动（文件/函数级）→ 理由 → 自检」

---

## 一、起点基线

| 项目 | 起点值 |
| --- | --- |
| 应用代码 | 8 493 行 / 441 个函数 |
| 最长函数 | 82 行（`core/hotkeys.py::_message_loop`） |
| 超过 60 行的函数 | 4 个 |
| 内联 `setStyleSheet` | 62 处 |
| 手写 `"#%02X%02X%02X"` | 5 处 |
| 重复代码行占比 | 17.00% |
| 主窗口构造 | 34.0 ms |
| 一次建议渲染（6 张卡片） | 40.5 ms |
| 一次建议计算 | 141.4 ms |
| 自动化测试 | 252 项（全绿） |

起点已存在的**真实缺陷**（本轮才发现并修复，不是"优化"，是 bug）：

1. 设置页从不与配置同步，控件停在各 SpinBox 的最小值 → 用户动一下任意开关，
   就把「6 条建议 / 3 组分 / ΔE 3.0」写成「1 条 / 1 组分 / 0.2」；
2. 设置页改容差/条数/模型后**不重算**，界面继续显示旧结果；
3. 「全部品牌」选项实际只搜 5 个首选品牌（`brands or None` 把空列表折成了 None）；
4. 手动输入非法颜色只把边框染红，失败原因藏在 tooltip 里；
5. 非首要建议在求解失败时退回单色，界面却标成「可直接瓶用」（ΔE 4.4 也叫"可直接用"）。

---

## 二、可优化项清单与优先级

评分 = 用户价值 ÷ 实现成本（各 1–5）。≥2.5 为 P0，1.5–2.5 为 P1，其余 P2。

### 用户体验

| # | 问题 | 价值 | 成本 | 优先级 |
| --- | --- | --- | --- | --- |
| A1 | 设置页初始值与真实配置不一致（数据丢失级） | 5 | 1 | P0 |
| A2 | 设置改动不触发重算 | 4 | 1 | P0 |
| A3 | 「全部品牌」名不副实 | 4 | 2 | P0 |
| A4 | 输入错误原因藏在 tooltip | 4 | 1 | P0 |
| A5 | 空状态无操作按钮 | 3 | 1 | P1 |
| A6 | 参数连续变更同步重算（拖动卡顿） | 4 | 2 | P1 |
| A7 | Toast 互相覆盖 | 3 | 1 | P1 |
| A8 | 无法在应用内微调颜色 | 4 | 3 | P1 |
| A9 | 参数命名/说明不清（只有 tooltip） | 3 | 2 | P1 |
| A10 | 无「恢复默认设置」入口 | 3 | 1 | P2 |
| A11 | 未取色时预览块显示假色值 | 2 | 1 | P2 |
| A12 | 计算中无可见反馈 | 2 | 1 | P2 |
| A13 | 空输入时「导入」仍可点 | 2 | 1 | P2 |

### 界面可视化

| # | 问题 | 价值 | 成本 | 优先级 |
| --- | --- | --- | --- | --- |
| B1 | 色卡条不换行、单项被拉成巨块、缺 ΔE | 4 | 2 | P0 |
| B2 | 只有 ΔE 数字，无刻度/分区/放大对比 | 5 | 2 | P0 |
| B3 | 色盘标记重叠且无标签，图例纯文字 | 4 | 2 | P0 |
| B4 | 历史色块在少条目时被拉成大方块 | 3 | 1 | P1 |
| B5 | 建议工具条在空状态下纵向拉满 | 3 | 1 | P1 |
| B6 | 用量页字段铺满整行、无用量的可视化 | 4 | 2 | P1 |
| B7 | 布局不随窗口尺寸变化 | 3 | 2 | P1 |
| B8 | 1366×768 / 125% 缩放下右栏被挤 | 3 | 2 | P2 |
| B9 | 图例无颜色块对应 | 3 | 2 | P2 |

### 代码质量

| # | 问题 | 价值 | 成本 | 优先级 |
| --- | --- | --- | --- | --- |
| C1 | 62 处内联 `setStyleSheet` 与 QSS 重复 | 3 | 2 | P0 |
| C2 | `_recompute` / `_recompute_async` 两条并行路径 | 3 | 2 | P0 |
| C3 | 过长函数（构造函数 70+ 行） | 3 | 2 | P1 |
| C4 | 手写 HEX 格式化 5 处 | 2 | 1 | P1 |
| C5 | `EmptyState.set_text` 用下标猜标签 | 3 | 1 | P1 |
| C6 | `ColorGrid` 列数在布局前计算且不随 resize 更新 | 3 | 2 | P1 |
| C7 | 参数变更无防抖 | 3 | 2 | P1 |
| C8 | 状态分散在 4 个字段 + 各面板各自持有 config | 3 | 3 | P2 |
| C9 | `hotkeys._message_loop` 82 行 Win32 循环 | 1 | 4 | 暂缓 |
| C10 | `suggest` 单次 126–141 ms | 3 | 3 | 暂缓 |

---

## 三、逐轮记录（36 轮）

### 正确性

#### R1 设置页与配置同步（A1）
**目标**：消除"动一个开关就把整套参数写成最小值"的数据丢失。
**改动**：`app/ui/panels/settings_panel.py::SettingsPanel.__init__` 末尾调用 `sync_from_config()`；
`app/ui/main_window.py::_build_ui` 再显式同步一次（双保险）。
**理由**：`SettingsPanel` 构造后从未读过 `AppConfig`，`_commit()` 却会把**所有**控件值写回配置，
于是"改一个复选框"等于"把没碰过的字段全部重置"。
**自检**：新增 `test_widgets_match_config_on_open` / `test_toggling_one_option_keeps_others`，
断言容差 4.5、9 条建议、2 组分、33 滴在改动前后都不变；截图确认设置页显示真实值。

#### R2 设置变更触发重算（A2）
**目标**：让"改设置"立刻生效。
**改动**：`SettingsPanel.settingsChanged` 新信号 → `_commit()` 末尾发出 → `MainWindow._on_settings_changed` 走异步重算。
**理由**：`_commit` 只存盘不发信号，用户改完容差回到建议页看到的还是旧结果，会以为功能坏了。
**自检**：`test_settings_change_triggers_recompute`（改容差后必须提交一次计算）。

#### R3 「全部品牌」语义修正（A3）
**目标**：让选项文案与行为一致。
**改动**：`services/paint_matcher.py::candidate_pool` 区分三态（`None`=首选品牌、`[]`=全库、`[..]`=指定品牌）；
`suggest` 增加 `brand_scope` 计算并透传给 `_build_suggestion`；`MainWindow._on_brand_filter_changed` 始终存盘。
**理由**：`keys = list(brands) if brands else list(config.preferred_brands)` 把空列表和 None 混为一谈，
UI 上选「全部品牌」实际只搜 5 家——选项在说谎。
**自检**：候选池从 5 品牌扩到 11 品牌 672 条；`test_candidate_pool_empty_brand_list_means_all_brands`、
`test_all_brands_scope_widens_alternatives`、`test_all_brands_option_passes_empty_scope`。

#### R4 「可直接瓶用」判定修正
**目标**：不再把 ΔE 4.4 的单色近似说成"可直接用"。
**改动**：`PaintSuggestion` 新增 `tolerance` 字段与 `is_within_tolerance`、`mode_label`；
卡片标题、`presenters.split_pair`、CSV `direct` 列统一改用 `mode_label` / `is_within_tolerance`。
**理由**：非首要建议求解失败时会 `build_direct_recipe` 退回单色，`recipe.direct=True`，
但 ΔE 可能远超容差；"可直接瓶用"是**结论**，不能只看"是不是单色"。
**自检**：截图中 ΔE 4.38 的卡片标题从「可直接瓶用」变为「单色近似（色差偏大）」；
`test_suggestion_is_direct_matches_recipe` 仍通过（`is_direct` 语义保持不变）。

#### R5 调色器回拖到基准色也要刷新
**目标**：消除"滑块回到原位、界面停在旧色"的错位。
**改动**：`ui/widgets/color_tuner.py` 增加 `_last_emitted`，`_emit_change` 改为与"上次发出的颜色"比较。
**理由**：原实现与**基准色**比较，拖回基准时直接 return，主窗口收不到信号。
**自检**：`test_drag_back_to_base_refreshes`（拖到 70 再拖回，样本必须回到原色）。

#### R6 计算失败与"没匹配到"区分
**目标**：算错时给出可操作提示，而不是"没有找到可用建议"。
**改动**：`services/async_suggest.py` 增加 `SuggestSignaller.failed`、`submit_suggest(on_error=...)`；
`MainWindow._on_suggest_failed` 显示「计算失败 + 原因 + 建议重试/换范围」，并带 token 去抖。
**理由**：异常被吞成空列表后，UI 无法区分"数据里确实没有"与"程序算崩了"。
**自检**：`test_task_reports_failure_instead_of_empty_list`、`test_failure_is_reported_not_shown_as_no_match`、
`test_stale_failure_is_ignored`。

#### R7 空状态文案不再残留
**目标**：`set_text` 传空描述时清空旧文案。
**改动**：`ui/widgets/empty_state.py` 保存 `_title/_description/_glyph` 引用，不再用 `findChildren()[1]` 猜下标。
**理由**：下标猜标签在"有没有 action 按钮"时顺序会变；空描述分支不更新标签，旧文案一直留着。
**自检**：`test_empty_state_text_updates_without_stale_description`。

### 边界情况

#### R8 ΔE 分级拒绝非有限值
**目标**：NaN/inf 不能被静默归到「完全不同的两个颜色」。
**改动**：`core/delta_e.py::grade_delta_e` 先做 `float()` + `isfinite` 判断，异常值返回「无法判定（色差数据异常）」。
**理由**：`value < limit` 对 NaN 恒为假，循环走到最后一级，把"数据坏了"说成"颜色差得远"。
**自检**：`test_grade_rejects_non_finite`（NaN / ±inf / None / "abc" 五种输入）。

#### R9 刻度尺的 NaN 指针
**目标**：非有限 ΔE 不画出一个"看不见的指针"。
**改动**：`ui/widgets/delta_gauge.py::DeltaGauge.set_value` 守卫 `isfinite`，异常值退化为空状态。
**理由**：NaN 坐标下 Qt 不报错但什么都不画，用户看到的是空白刻度尺。
**自检**：`test_gauge_accepts_value_and_none`（含 None 与正常值两次 `grab()`）。

#### R10 历史色块行高被拉伸
**目标**：只有 1–2 条记录时色块不再变成 200 px 高的大方块。
**改动**：`ui/panels/library_panel.py::_Chip` 改 `setFixedHeight(58)`；`ColorGrid._rebuild` 末尾
`setRowStretch(rows, 1)` + `setColumnStretch(columns, 1)` 吸收多余空间。
**理由**：`QGridLayout` 在 `QScrollArea(widgetResizable=True)` 里会把行撑满。
**自检**：900×1000 截图里两行色块保持 58 px；`test_chip_height_is_fixed`。

#### R11 色卡条不换行 / 单项被拉成巨块
**目标**：任意宽度下色卡都可读。
**改动**：`ui/widgets/swatch_card.py::SwatchStrip` 改为按宽度算列数的 `QGridLayout`，
`resizeEvent` 重排；`_Swatch` 设 `setMaximumWidth(168)`。
**理由**：固定单行 + `Expanding` 策略：窄窗口下压成细条，1 个色块时占满半屏。
**自检**：`test_columns_shrink_with_width`、`test_narrow_width_still_wraps_into_rows`、
`test_single_item_not_stretched_to_full_width`；1024×720 截图确认 4 项仍在一行。

#### R12 色盘标记重叠
**目标**：5 个相近色号不再糊成 2 个点。
**改动**：`ui/widgets/color_wheel.py::ColorWheel._resolve_overlaps` 改为"以原位置为圆心逐圈找空位"，
优先沿半径外推、找不到再左右偏转，并画虚线引线指回真实位置。
**理由**：只沿半径推，对"色相接近"的点无效（各自沿自己的射线走，距离不变）。
**自检**：`test_overlapping_markers_are_pushed_apart`（5 点两两间距 ≥ 12 px）。

#### R13 手动输入的错误反馈
**目标**：非法输入当场说清原因与可接受格式。
**改动**：`ui/panels/pick_panel.py` 新增 `_error` 标签、`_show_error/_clear_error`、`_on_input_changed`。
**理由**：原来只 `setStyleSheet(红边)` + `setToolTip`，要悬停才知道为什么失败。
**自检**：`test_invalid_input_shows_inline_reason`、`test_error_clears_when_typing`；19-error 截图。

#### R14 空输入时的「导入」按钮
**目标**：按钮状态与可用性一致。
**改动**：`_input.textChanged` → `setEnabled(bool(text.strip()))`，初始禁用。
**理由**：点了没反应比禁用更让人困惑。
**自检**：`test_empty_input_keeps_import_disabled`。

### 性能

#### R15 参数连续变更的重算风暴
**目标**：拖动 SpinBox 不再卡死。
**改动**：`MainWindow` 增加 180 ms 单次 `QTimer`（`_compute_timer`）；`_request_compute(immediate)` 统一入口：
吸色立即算、参数防抖算；`_on_coverage_changed` 走防抖分支。
**理由**：一次拖动触发几十次 `valueChanged`，每次同步 130 ms 计算，界面完全失去响应。
**自检**：`test_rapid_parameter_changes_compute_once`（连续 20 次变更 → 只提交 1 次计算）；
`test_pick_is_immediate`（吸色仍立即算）。

#### R16 建议卡片的渲染开销
**目标**：连续吸色时渲染不拖后腿。
**改动**：
1. `SuggestPanel` 改为**卡片池**（`_ensure_cards`），条数不变时只更新数据；
2. `SwatchStrip` 在数量/列数不变时**原地更新** `_Swatch`（`update_item`）；
3. `_Swatch` 改为纯自绘，去掉两个带 `setStyleSheet` 的 QLabel；
4. 用量芯片固定建 8 个复用，不再每次 deleteLater + 新建；
5. 宽度未知时跳过首次重建，避免"建两遍"。
**理由**：`cProfile` 显示 6 张卡片的渲染里，控件创建/销毁与样式解析占七成以上。
**自检**：一次建议渲染 **40.5 ms → 11.3 ms（-72%）**；截图与 307 项测试无回归。

#### R17 设置页的无关重算
**目标**：改「历史保留条数」不触发 130 ms 重算。
**改动**：`SettingsPanel._match_signature()` 只包含影响匹配的 8 个字段，签名变化才发 `settingsChanged`。
**理由**：`_commit` 连接了所有控件，任何字段变更都会重算。
**自检**：`test_irrelevant_setting_does_not_recompute`、`test_matching_setting_does_recompute`。

#### R18 内联样式解析
**目标**：把 46 处重复的标签颜色声明收回到 QSS。
**改动**：`ui/theme.py` 增加 `QLabel { background: transparent }` 与 `#Chip / #ChipAccent / #HintLabel / #ErrorLabel` 角色；
批量把 `setStyleSheet(f"color: {Palette.x}; background: transparent;")` 改成 `setObjectName(...)`。
**理由**：同一套颜色在 46 个地方各写一遍，改主题要改 46 处；每个控件都要解析一次样式表。
**自检**：内联 `setStyleSheet` **62 → 27 处**；主窗口构造 34.0 → 42.0 ms（新增控件后仍 < 50 ms）；
`test_no_duplicate_inline_label_colors` 守卫；截图逐页核对配色未变。

### 完整性

#### R19 空状态就地操作
**目标**：空状态给出"下一步"，而不是让用户回左栏找按钮。
**改动**：`EmptyState` 支持 action 按钮与 `set_action`；建议面板/色卡对比/历史收藏的空状态都挂上「开始吸色」，
通过 `pickRequested` 信号接到 `MainWindow._start_picking`。
**理由**：空状态最该做的事是"就地开始"。
**自检**：`test_empty_states_offer_pick_action`、`test_empty_action_is_wired_to_pick`（点按钮真的发出信号）。

#### R20 调色微调器
**目标**：让"再亮一点/再灰一点"变成一次拖动，而不是重吸或手算 HEX。
**改动**：新增 `ui/widgets/color_tuner.py`（H/S/V 三滑块 + 还原，120 ms 防抖）；
`PickPanel` 折叠式接入；`MainWindow._on_tune_changed/_on_tune_reset` 走 `_SOURCE_TUNE` 分支
（不写历史、不自动复制、不重置滑块）。
**理由**：屏幕色与漆膜有色差，用户经常需要试算"稍微偏一点能不能直接买到"。
**自检**：`test_tuning_changes_target_without_history`、`test_reset_restores_base_color`；
操作步骤从 4 步（读 HEX → 心算 → 输入 → 回车）降到 1 步。

#### R21 色差刻度尺
**目标**：把 ΔE 从"要背阈值"变成"看一眼"。
**改动**：新增 `ui/widgets/delta_gauge.py::DeltaGauge`：按 1/2/3.5/5 分级画色带 + 刻度 + 指针，
指针颜色取自分级色；每张建议卡片与色卡对比页都接入。
**理由**：ΔE 是专业指标，2.96 到底算不算能用，用户没有参照系。
**自检**：截图确认指针落在"近距离可见差异"（琥珀色）区间；`test_gauge_accepts_value_and_none`。

#### R22 分割对比 + 色差放大
**目标**：让"色差方向"可见。
**改动**：`SplitPreview`（左右分割 + 接缝白线 + 两侧 HEX）与 `AmplifiedDiff`（Lab 差值 ×4 放大块），
组合成 `DeltaCompare` 卡片，放在色卡对比页顶部。
**理由**：并排两块色更容易看出差异；放大块把 1–2 的 ΔE 变成肉眼可辨的偏色方向。
**自检**：`test_amplified_diff_actually_amplifies`（放大后的 Lab 距离必须大于原始距离）、
`test_amplified_diff_survives_extremes`（纯黑/纯白互放不崩）。

#### R23 编号标注体系
**目标**：色卡、色盘、图例用同一套编号，不再靠颜色猜对应关系。
**改动**：新增 `ui/presenters.py`（`build_swatches/build_markers/build_legend/split_pair`），
卡片与色卡对比页共用；`SwatchItem.index`、`WheelMarker.index`、`index_badge()`。
**理由**：两个面板各写一套组装逻辑，编号迟早漂移；编号统一后"③ 是哪个点"不再需要猜。
**自检**：`test_swatch_and_marker_numbering_match`、`test_legend_lines_match_swatches`、`test_target_is_always_first`。

#### R24 恢复默认设置
**目标**：给"调乱了"一个出口。
**改动**：`SettingsPanel._build_misc_section` 增加按钮 → `_on_restore_defaults()`：
`config.reset_to_defaults()` + 存盘 + 重新同步控件 + 发 `settingsChanged/hotkeysChanged`。
**理由**：`AppConfig.reset_to_defaults()` 早就实现并有测试，但 UI 从未接线。
**自检**：`test_restore_defaults`。

#### R25 多色配方的"每支漆多少 ml"
**目标**：补回被我第一版芯片丢掉的组分用量。
**改动**：`SuggestionCard._render_usage` 追加 `{色号} {ml}` 芯片（芯片池扩到 8）；
`export_service._component_amounts` 同步写进 Markdown；分享文本追加 `≈x.x ml`。
**理由**：调 15:5 的配方，用户真正要的是"6.24 ml + 2.29 ml"，而不是"再按比例算一遍"。
**自检**：`test_multi_component_recipe_shows_per_paint_ml`、`test_share_text_includes_component_amounts`。

#### R26 键盘切页
**目标**：吸色时手不用离开键盘。
**改动**：`MainWindow._build_menu` 给「视图」菜单项加 `Ctrl+1..4` 快捷键。
**理由**：四个页签是高频切换目标，菜单里同时暴露快捷键也更易发现。
**自检**：`test_view_menu_has_number_shortcuts`。

#### R27 计算中状态
**目标**：连续吸色时看得出"还在算"。
**改动**：`SuggestPanel.set_busy(True/False)` 在计数位显示「计算中…」并变色，不清空已有卡片。
**理由**：只在状态栏说一句，视线在结果区时看不到。
**自检**：截图与 `set_suggestions` 末尾复位逻辑；`test_apply_color_renders_suggestions` 仍通过。

### 可读性

#### R28 参数命名与说明
**目标**：把"只有作者看得懂"的参数讲清楚。
**改动**：`ui/widgets/form_row.py`（`form_label/with_hint/hint_label`）；
`CoveragePanel` 改名（单位用量→每层每平米用量、余量系数→调漆余量）+ 每项一行说明 + 快速套用预设
（1/35 战车 / 1/100 飞机 / 1/6 手办）；`SettingsPanel` 同步加说明。
**理由**：说明全塞在 tooltip 里，等于没有说明；面积是最难估的参数，给锚点比让用户瞎填有用。
**自检**：截图确认说明与控件同行、不压字；`test_widgets_match_config_on_open` 覆盖字段绑定。

#### R29 长函数拆分
**目标**：把 60+ 行的构造函数拆成可读的构建步骤。
**改动**：`PickPanel.__init__` → `_build_title/_build_preview_block/_build_pick_block/_build_input_block/
_build_error_label/_build_action_block/_build_tuner/_build_readout`；
`ColorTuner.__init__` → `_build_header/_build_body/_build_channel_row/_build_footer`；
`CoveragePanel._build_form` → `_add_area_field/_add_coat_fields/_add_material_fields`；
`ColorWheel.paintEvent` → `_paint_wheel/_paint_markers/_paint_marker/_paint_crosshair/_paint_badge`；
`DeltaGauge.paintEvent` → `_paint_bands/_paint_ticks/_paint_pointer`；
`SuggestionCard.set_suggestion` → `_render_header/_render_swatches/_render_ratio/_render_usage/_render_alternatives`。
**理由**：构造函数把"布局"和"逻辑"混在一起，改一处要在 70 行里找位置。
**自检**：`test_function_length_budget`（≤60 行，白名单仅 Win32 两处）；
超过 60 行的函数 **4 → 2**（且都在白名单里）。

#### R30 图例色块化
**目标**：图例不再是一串 `●` 字符。
**改动**：`VisualizePanel._LegendRow`：真实色块 + 编号 + 文本，随建议重建。
**理由**：纯文字图例要用户自己在脑子里把"●"映射到色盘上的点。
**自检**：截图确认 4 行图例色块与色卡编号一致。

#### R31 比例条文字压字
**目标**：段内文字不再被裁掉一半。
**改动**：`ui/widgets/ratio_bar.py` 改为单行 `色号 · 滴数`，宽度不足时用 `elidedText` 省略。
**理由**：原实现"标签居中 + 滴数贴底"，在 34 px 高的条里两行互相压，滴数被裁。
**自检**：截图确认「71.024 · 15 滴」「H-37 · 5 滴」完整可见。

#### R32 绘制上下文统一
**目标**：8 个自绘控件的 `QPainter` 生命周期只剩一处定义。
**改动**：新增 `ui/paint.py::painter_on()`（上下文管理器，必定 `end()`），
改造 `swatch_card/ratio_bar/color_wheel/delta_gauge/pick_panel/usage_bar` 的 `paintEvent`。
**理由**：`paintEvent` 中途抛异常时 `end()` 不会执行，Qt 会报 "Painter already active" 并画出空白帧；
抗锯齿也靠每处手写，漏一处就有一个控件边缘发毛。
**自检**：`test_wheel_paints_without_error`、截图逐页核对；`usage_bar` 命名冲突（`self._paint` 浮点属性 vs `_paint` 方法）
在自检阶段被截图发现并改名为 `_draw`——这条记下来是因为它说明"只跑单测不看图"会漏掉绘制层问题。

### 一致性

#### R33 Toast 堆叠
**目标**：连续操作时每条反馈都看得见。
**改动**：`ui/widgets/toast.py` 重写：按父窗口维护栈（`WeakKeyDictionary`），纵向排布、
同文案续命不重复、最多 3 条、父窗口 resize 自动重排。
**理由**：原来所有 Toast 都在右下角同一位置，后一条完全盖住前一条。
**自检**：`test_two_messages_stack_without_overlap`、`test_same_message_does_not_duplicate`、
`test_stack_is_capped`。

#### R34 HEX 格式化统一
**目标**：颜色字符串只有一个生成入口。
**改动**：`paint_db.PaintEntry.hex`、`recipe_engine.Recipe.mixed_hex`、`library_panel._text_color`、
`pick_panel._Preview` 全部改用 `rgb_to_hex`；`visualize_panel._hex` 删除。
**理由**：手写 `"#%02X%02X%02X"` 5 处，改格式（大小写/前缀）要改 5 处。
**自检**：手写格式化 **5 → 0**；`test_no_manual_hex_formatting` 守卫。

#### R35 摘要与卡片精度一致
**目标**：状态栏与卡片不再出现 2.96 / 3.0 两个数。
**改动**：`paint_matcher.summarize` 统一 `:.2f`。
**理由**：同一份计算结果两个精度，用户会以为是两次不同的计算。
**自检**：截图状态栏显示 ΔE 2.96，与卡片一致。

#### R36 快捷方式自安装的"还原"而非"删除"
**目标**：重建失败时不要弄丢用户桌面上的入口。
**改动**：`core/shortcut.py` 抽出 `_read_target` / `_restore_or_drop`；
`ensure_desktop_shortcut` 在改动前先备份原 lnk 字节，校验失败时**还原**原文件（没有原文件才删半成品）；
另加一条短路：COM 读不出目标、但 lnk 字节里确实写着本 exe 时直接判定"已就绪"，不再反复删除重建。
**理由**：这是打包后真实日志里暴露的问题——受限环境（沙箱/安全软件）下 COM 回读经常失败，
旧逻辑会「删掉 → 重建 → 校验失败 → 再删掉」，每次启动都把用户桌面上的入口折腾一遍；
万一用户原来就有同名快捷方式，等于被程序删了。
**自检**：`test_keeps_existing_lnk_when_com_read_fails_but_bytes_match`、
`test_restores_previous_lnk_when_new_one_fails_validation`（断言原字节被完整还原）；
打包版启动日志从「已删除半成品」变为「已还原原文件 / 按字节校验已就绪」。

---

## 四、最终结果

### 门禁

```
pyflakes app scripts tests run.py   → 零输出
unittest discover -s tests          → 307 项全绿（起点 252 项）
scripts/smoke_test.py               → 12 项全 PASS
scripts/quality_metrics.py          → 见下表
scripts/screenshot.py               → 10 张离屏截图逐张核对
```

### 指标对比

| 指标 | 起点 | 终版 | 变化 |
| --- | --- | --- | --- |
| 自动化测试 | 252 | **307** | +55（含 4 类规范守卫） |
| 一次建议渲染 | 40.5 ms | **11.3 ms** | **-72%** |
| 一次建议计算 | 141.4 ms | 129.8 ms | -8% |
| 主窗口构造 | 34.0 ms | 44.1 ms | +30%（新增刻度尺/微调器/芯片） |
| 内联 `setStyleSheet` | 62 处 | **27 处** | -56% |
| 手写 HEX 格式化 | 5 处 | **0 处** | -100% |
| 超过 60 行的函数 | 4 个 | **2 个** | -50%（余下均在白名单） |
| 最长函数 | 82 行 | 82 行 | 不变（Win32 消息循环，白名单） |
| 应用代码 | 8 493 行 | 10 120 行 | +19%（新增 10 个模块） |
| 重复代码行占比 | 17.00% | 18.26% | +1.26pt（见下说明） |

**关于重复率的说明**：这个指标统计"同一行出现在 ≥2 处"的原始行数。本轮新增的
10 个模块里大量是框架样板（`def __init__(self, parent=None)`、`painter = QPainter(self)`、
`layout = QVBoxLayout(self)`），把比例推高了 1.25 个百分点。
真正造成维护成本的**语义重复**已经清零：颜色字符串格式化 5→0、标签配色 46→0、
`QPainter` 生命周期 8→1、色卡/色盘/图例组装 2→1、计算路径 2→1、
快捷方式"备份/还原"两处收口到 `_restore_or_drop` 1 处。
因此这个指标在本轮**不作为优化目标**，只作为"没有大量复制粘贴"的粗筛。

### 用户可感知的变化

| 场景 | 起点 | 终版 |
| --- | --- | --- |
| 想让颜色"再亮一点" | 重吸 / 手算 HEX 再输入（4 步） | 拖一下明度滑块（1 步） |
| 判断 ΔE 2.96 能不能接受 | 查阈值表 | 刻度尺上直接看落点 + 分割对比 + 放大块 |
| 手动输入写错 | 红边框，原因藏在 tooltip | 当场显示「支持 #RRGGBB / rgb() / hsl() …」 |
| 拖动面积参数 | 每次 tick 重算 130 ms，卡顿 | 防抖 180 ms，只算 1 次 |
| 连续复制两样东西 | 后一条提示盖住前一条 | 两条上下堆叠 |
| 空状态 | 只有一句说明 | 说明 + 「开始吸色」按钮 |
| 改设置 | 可能把参数写成最小值；改完不生效 | 与配置一致；改完立即重算 |
| 选「全部品牌」 | 实际只搜 5 家 | 真的搜 11 家 672 条 |
| 看替代色号 | 「● AV-MA 71.024」纯文字 | 编号 + 真实色块，与色卡/色盘一一对应 |
| 调 15:5 的配方 | 只给比例，自己换算 ml | 直接给「71.024 6.24 ml / H-37 2.29 ml」 |

---

## 五、暂缓项与后续路线

| 项 | 原因 | 建议时机 |
| --- | --- | --- |
| **状态集中化**（把 `_sample/_suggestions/_brand_filter/_suggest_token` 收进 `AppState`） | 需要新增一层状态对象并改所有面板的读写点，收益在可维护性而非用户可见；本轮已用"单一计算路径 + 单一颜色入口"消掉最痛的重复 | 下一次结构性重构，配合新功能一起做 |
| **`suggest` 再提速**（126 ms） | 热路径已做过 K/S 预计算、三色剪枝、线性缓存；再往下要 numpy 向量化或 C 扩展，收益 < 维护成本，且会破坏"纯 Python 可读" | 若用户反馈"吸色后等待感明显"再做 |
| **`hotkeys._message_loop`（82 行）/ `shortcut._com_create`（64 行）** | Win32 消息循环与 COM 调用是成对的阻塞过程，拆开更难保证正确性；且本环境无显示器，改动无法回归验证 | 有真实 Windows 桌面回归环境时 |
| **A/B 两色对比**（拿收藏色与当前色比 ΔE） | 需要新增"第二颜色槽"状态与入口，价值低于已完成的四项色差可视化 | 下一轮 UX 迭代首选 |
| **高 DPI 完整适配** | 已做最小窗口 960×600、左栏 28% 自适应、`PassThrough` 缩放策略；逐控件字号/间距适配需要多分辨率实机截图核对 | 收集到 125%/150% 实机反馈后 |
| **色号库扩充**（672 → 1000+） | 属数据工作，与代码质量迭代正交；需要逐条核对官方色卡 | 独立的数据迭代轮次 |

### 下一阶段验收标准（建议）

1. `pyflakes` 零输出、`unittest` 全绿、`smoke_test` 全 PASS 三件套不可退化；
2. `quality_metrics.py` 中 `manual_hex` 恒为 0、`inline_style` 不再回升、`render_ms` 不超过 20 ms；
3. 任何新增界面必须同时提供：空状态文案、错误文案、以及至少一张 `screenshot.py` 截图；
4. 新增的"结论性文案"（可直接瓶用 / 可接受 / 需调配）必须由数据属性推导，不允许在 UI 里写死判断。
