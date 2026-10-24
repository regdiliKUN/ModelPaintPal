# 落地方案：输出数据可靠性 + 联网能力

> 适用对象：ModelPaintPal（3D 打印模型涂装配色助手）
> 源码位置：`C:\Users\xukunhang\WorkBuddy\2026-10-21-02-24-03\ModelPaintPal`
> （`%LOCALAPPDATA%\Programs\ModelPaintPal` 只是 PyInstaller 打包产物，不是源码）

## 实现状态（P0–P5 已全部落地）

| 期 | 状态 | 落地位置 |
| --- | --- | --- |
| P0 数据契约 + 来源注册表 | ✅ | `app/data/sources.py`（新）、`paint_seed.py` 契约扩展、`paint_db.py` 四字段 + 8/12 元组兼容 |
| P0 反编造自检 | ✅ | `scripts/check_paint_db.py` 重写（problems 阻断 / warnings 提示两分） |
| P1 来源聚合 + 证据分级 | ✅ | `app/services/provenance.py`（新）、`alternatives.py::evidence`、`paint_matcher.py::provenance` |
| P1/P2/P3 界面与导出 | ✅ | `app/ui/widgets/provenance_box.py`（新）、`suggestion_card.py`、`export_service.py`、`coverage.py::ANCHORS` |
| P4 联网核实 | ✅ | `app/core/http_client.py`、`app/data/verify_cache.py`、`app/services/verify_service.py`、`async_verify.py`、`app/ui/panels/verify_dialog.py` |
| P5 库更新 diff | ✅ | `scripts/update_paint_db.py` |

**两处与本文初稿不同的实现取舍（都是往更保守的方向改的）：**

1. **溯源标注走 `sources.ENTRY_SOURCES`，不动 672 行种子数据。**
   原文说改 12 元组，实际只把 12 元组作为**格式支持**保留，真正补数据走一张小的
   按 uid 索引的标注表。改错一张小表的代价，远小于改错 672 行。
2. **联网不内置任何抓取端点。** 各品牌官网结构各异且有 Cloudflare 拦截，凭空写
   URL 抓不到是常态，还会让人误以为功能在工作。机制（并发/去重/排序/降级/缓存）
   全部实现并可测，核验源由用户在 `userdata/verify_providers.json` 配置；
   未配置时界面如实说「未配置核验源」。

当前色号库只有 6 条已标注来源（`DATA_ITERATIONS.md` 里有明确交叉校验记录的
那几条），其余 666 条处于「未标注」状态 —— 自检会对此报警。这是**数据缺口**，
不是功能缺陷。

---

## 0. 结论摘要

| 需求 | 是否适用 | 结论 |
| --- | --- | --- |
| 数据可靠性（来源可追溯 / 事实与推断区分 / 不确定性与置信度 / 一致性校验） | **高度适用，且是当前真实缺口** | 建议做，本文给出模块级方案 |
| 联网搜索（检索触发判断 / 查询改写 / 多源并行 / 去重排序 / 限流降级缓存） | **前提不成立** | 不建议照抄联网问答产品。建议降级为「单条色号核实」+「色号库更新 diff」，见第 3 节 |

一句话：**这个软件缺的不是"检索"，是"溯源"。** 库里 672 条色号的每一个 hex，目前都无法回答"这个数字从哪来"——但 22 轮检索的过程全写在 `docs/DATA_ITERATIONS.md` 里，只是没有下沉到数据结构。这是本次最值得补的一层。

---

## 1. 现状勘查（硬事实）

### 1.1 已有的底子（不要重造）

- **校准回路**：`paint_db.calibrate(uid, hex)` 把用户试喷实测值写入 `user_overrides.json`，放在用户目录，不污染随包数据（`paint_db.py:264`）。这是"把误差交还给用户"的成熟机制。
- **自检脚本**：`scripts/check_paint_db.py` 已做字段数 / hex 正则 / 取值域 / 同品牌重复 / 品牌存在性校验。
- **替代色号双证据链**：`alternatives.py` 分「同标准色号」与「跨品牌 ΔE 最近色」两路。
- **ΔE 分级**：CIEDE2000 + 五档人眼可辨分级。
- **可复现性强约定**：`paint_db.by_brands()` 明确拒绝用 `set()` 迭代，因为哈希随机化会让候选顺序漂移（源码注释 `paint_db.py:171`）。**任何新增聚合逻辑都必须遵守这条。**

### 1.2 真实缺口

| # | 缺口 | 证据 |
| --- | --- | --- |
| G1 | 色号记录 **零溯源字段** | `paint_seed.py` 数据契约为 8 元组 `(code, 中文名, 英文名, hex, finish, opacity, standards, note)`，没有任何"来源"字段 |
| G2 | **不同可信度的色值混在一起无法区分** | `DATA_ITERATIONS.md` 第 9 轮："本库多处以 paintatlas / paint-vault 的取值替换了原先的估算值"——替换后看不出哪条是实测值、哪条仍是估算 |
| G3 | **"可追溯性收尾"其实没收尾** | `DATA_ITERATIONS.md` 第 22 轮写的是"能显示来源品牌、漆基、光泽、遮盖力"——那是**属性**，不是**来源** |
| G4 | 用量锚点是硬编码常量，来源只在文档里 | `coverage.py`：`APPLICATION_FACTORS` 1.35/1.05/1.60、`SURFACE_FACTORS` 1.30/1.10、默认 `110 ml/m²/层` |
| G5 | 两条证据链在 UI 上强度等价 | `alternatives.py:106` 最终按 `(有无共享标准色, ΔE)` 排序，`suggestion_card.py:229` 只渲染 `alt.reason` 文本——"官方标准色一致"和"碰巧颜色接近"看起来一样 |
| G6 | 导出/分享文本不带来源 | `export_service.py` 产出 JSON / Markdown / CSV / TSV / 分享文本，均不含来源信息。分享文本是发群用的，**最需要可追溯** |
| G7 | 零网络能力 | `requirements.txt` 仅 PySide6 / Pillow / numpy / mss；全仓 `app/` 无 HTTP 客户端；`brands.py` 里的 url 是纯展示字符串 |

---

## 2. 数据可靠性方案

### 2.1 核心设计决策：引用编号制，而不是每条塞 URL

672 条色号如果每条都内联一个完整 URL，会带来三个问题：数据体积膨胀、URL 失效后要改 672 处、以及**无法做一致性校验**。

采用论文参考文献的做法：

```
paint_seed 行内只存来源 ID（如 "S:gsi-h-official"）
真正的来源元数据集中在 sources.py 注册表里
```

- 改 URL 只需改一处
- 自检可以断言「**色号引用的来源 ID 必须在注册表中存在**」→ 这是"不得编造来源"的机械保证
- 来源列表天然去重，正好对应 UI 上的"来源列表展示"

### 2.2 数据契约改造（8 元组 → 12 元组）

```
(code, 中文名, 英文名, hex, finish, opacity, standards, note,
 src_kind, src_ref, src_date, confidence)
```

**向后兼容是硬要求**：672 条数据不可能一次补完。`_build_from_seed()` 解包处做长度判断：

```python
if len(row) == 8:
    row = (*row, "derived", "", "", None)   # 未标注的一律按最低档"推定"处理
```

> 这一条很关键：**未标注 = 推定，而不是未标注 = 可信**。默认压低而不是默认抬高，才符合"数据不足就认"的项目原则。

#### `src_kind` 取值域（六档）

| 取值 | 含义 | 默认置信度 | 性质 |
| --- | --- | --- | --- |
| `official` | 厂家官网目录 / 官方转换表 | 0.85 | 事实引用 |
| `standard` | FS / RAL / RLM / BS 公开色度数据 | 0.80 | 事实引用 |
| `retail` | 授权经销 / 零售目录 | 0.75 | 事实引用 |
| `chart` | 第三方数字化色卡站（paint-vault / paintatlas） | 0.70 | 事实引用 |
| `derived` | 按同系色推定 | 0.45 | **推断** |
| `calibrated` | 用户试喷实测 | 0.90 | 事实引用（本机） |

### 2.3 「事实引用 vs 推断」在这个软件里的准确切分

这是本次方案里最需要想清楚的一点。用户要求的"区分事实引用与模型推断"，在本软件对应**两类完全不同的推断**，UI 上必须用两套视觉语言：

| 类别 | 内容 | UI 表达 |
| --- | --- | --- |
| **事实引用** | 色号存在性、hex 色值、标准色号、容量、漆基 | 上标数字角标 ①②③，可点开看来源名 / 链接 / 日期 |
| **推断 A：数据推定** | `src_kind = derived` 的色值 | 角标变灰 + "推定" 字样，置信度 chip 转橙 |
| **推断 B：计算推定** | 配方比例（Kubelka-Munk 求解）、用量估算、跨品牌最近色 | **不用角标**，改用斜体 + "推算" 前缀，并在提示里写出公式与锚点 |

把"算出来的"也挂上引用角标是错的——它没有一个可被点击的来源，用户点了会以为有据可查。

### 2.4 模块改动清单

| 模块 | 改动 | 影响面 |
| --- | --- | --- |
| **新增** `app/data/sources.py` | 来源注册表：`SOURCES = {id: {name, url, kind, accessed, note}}` | 纯新增 |
| `app/data/paint_seed.py` | `Row` 类型扩到 12 元组；文档字符串更新 | 类型定义 |
| `app/data/paint_db.py` | `PaintEntry` 加 `src_kind / src_ref / src_date / confidence` 四字段；新增 `provenance` property；`to_dict/from_dict` 同步扩展；`_build_from_seed()` 长度兼容 | **中**——`to_dict` 是导出链路的数据源 |
| 新增 `app/services/provenance.py` | 把一条建议涉及的所有来源聚合、去重、编号 | 纯新增，但需遵守可复现约定 |
| `app/services/paint_matcher.py` | `PaintSuggestion` 增加 `provenance_summary`（锚点 + 配方组分 + 替代色的来源并集，稳定排序后编号） | 建议对象结构 |
| `app/services/alternatives.py` | `Alternative` 增加 `evidence` 字段（`standard` / `nearest`）；`reason` 文案体现强度差 | 替代色排序与文案 |
| `app/services/coverage.py` | 三个因子表加来源注释常量化 `*_SOURCE`；`notes` 里补"锚点来自汽车底色漆工艺数据，模型漆膜更薄，建议校准" | 提示文案 |
| `app/data/brands.py` | `url` 升级为来源注册表权威入口；补 `catalog_url`（官网首页对"查某个色号"没用） | 展示字段 |
| `scripts/check_paint_db.py` | 新增溯源断言（见 2.6） | 门禁 |
| `app/ui/panels/suggestion_card.py` + `app/ui/widgets/` | 来源角标、置信度 chip、证据强度、可折叠来源区 | **UI 高度变化** |
| `app/services/export_service.py` | 全部导出格式带来源；分享文本末尾附来源列表 | **导出 schema** |

### 2.5 对现有功能的影响（风险点）

1. **`Row` 元组变长** → `paint_db._build_from_seed`、`check_paint_db.py`、以及 `tests/test_data_integrity.py` / `test_paint_db.py` 里的解包处都要改。**必须保留 8 元组兼容分支**，否则 305 项测试会一次性全红。
2. **导出 JSON schema 变化** → 只新增字段、不改旧字段名，保证旧版导出文件仍能被读。`from_dict` 对新字段全部给默认值。
3. **UI 卡片变高** → `scripts/screenshot.py` 的视觉回归基线需要重拍（10 张）。
4. **未标注数据会被集体压到 0.45 置信度** → 初次上线时界面可能大面积显示"推定"，观感上像"质量变差了"。**建议分两步**：先把 `derived` 显示为"未标注来源"的温和提示，数据补齐后再切换到严格置信度展示。这条要提前跟用户打招呼。
5. **性能** → 672 条多 4 个小字段可忽略；`provenance_summary` 必须在 `PaintSuggestion` 构建时算一次并缓存，不要每次渲染重算。

### 2.6 验证方式

沿用项目既有门禁（`pyflakes` 无输出 + `unittest` 全绿 + 冒烟 12 项 + 色号库自检），新增：

| 层 | 测试 | 断言 |
| --- | --- | --- |
| `test_data_integrity.py` | 溯源字段取值域 | `src_kind` 不在六档内 → 失败 |
| `test_data_integrity.py` | **反编造（最关键）** | `src_ref` 指向注册表中不存在的 ID → **必须失败**；`src_kind != derived` 但 `src_ref` 为空 → **必须失败** |
| `test_data_integrity.py` | 孤儿来源检测 | 注册表中无任何色号引用的来源 → 报警（不阻断） |
| `test_data_integrity.py` | 一致性：数字 | 抽样 N 条，比对 `hex` 与来源注册表中记录的参考值，ΔE 超阈值 → 报警 |
| `test_data_integrity.py` | 一致性：时间 | `src_date` 早于 24 个月 → 必须带"数据可能过期"标记 |
| `test_data_integrity.py` | 一致性：专有名词 | 标准色号必须落在 `STANDARD_PREFIXES` 域内；品牌 key 必须在 `BRANDS` 中存在（已有，扩到新字段） |
| `test_matcher.py` | 聚合稳定性 | 同一输入多次构建 → 引用编号顺序**逐位一致**（遵守 `by_brands` 的可复现约定） |
| `test_matcher.py` | 置信度传播 | 全 `derived` 组分 → 建议必须带低置信标记；混入 `calibrated` → 置信度必须提升 |
| `test_matcher.py` | 推断不挂角标 | 计算类结论（配方 / 用量）的 provenance 引用集合必须为空 |
| `test_matcher.py` | 8 元组兼容 | 喂入旧 8 元组 → 不崩溃，且置信度被压到 `derived` 档 |
| `scripts/check_paint_db.py --strict` | 门禁加严 | 上述溯源断言全量跑一遍 |
| `scripts/screenshot.py` | 视觉回归 | 重拍基线并逐张核对 |

---

## 3. 联网能力：为什么不建议照做，以及建议做什么

### 3.1 前提不成立

- 现在**零网络栈、零 LLM**。要"优化检索触发判断 / 查询改写 / 多轮上下文消解 / 去重排序 / 限流降级"，是**从零新建一整套检索中间件**，不是优化。
- 这软件的价值是「吸一个色 → 立刻出配方」，是**即时工具**，不是**问答产品**。用户吸完色不会想再"搜一下"。塞个检索框进来，是把工具变成聊天窗。
- 色号库是**慢变数据**（品牌目录一年更新不了几次），不是新闻或股价。慢变数据适合"周期性更新 + 人工确认入库"，不适合"运行时实时检索"。

### 3.2 隐私红线（必须写死）

这个软件用 `mss` **抓全屏取色**。一旦联网，用户第一反应就是"我的屏幕会不会被传出去"。

> **硬约束：任何联网请求只允许发送 `{品牌, 色号, 标准色号}` 这类文本查询，禁止发送任何位图、像素数据或屏幕截图。**
> 联网总开关默认关闭，复用已有的 `check_updates_on_start` 配置项语义，且在设置页明确写出这条约束。

### 3.3 建议的两个能力（都比"搜索"窄得多，但都是真需求）

**A. 单条色号核实（运行时，按需，显式触发）**
- 落点：建议卡片加一个「核实来源」按钮。
- 行为：只发 `{brand, code}` 文本 → 多源并行 → 展示各源返回的色值与本地值的 ΔE → **不自动改本地数据**，用户点"采用"才走已有的 `calibrate()` 回路写入。
- 这才是真正需要"多源并行 / 去重 / 排序 / 超时降级 / 缓存"的地方，而且规模小、可降级。

**降级链（必须逐级明确，不能含糊过去）**

| 情况 | 行为 |
| --- | --- |
| 全部成功 | 列出各源色值与 ΔE，标注与本地值最接近的源 |
| 部分源超时 / 429 | 展示已成功的源，并明确写「N 个源未响应 / 被限流」 |
| 全部失败（超时 / 断网 / 解析失败） | **明确说"未能核实，当前值仍是 XX 来源于 YYYY-MM 的数据"**，本地值一字不改 |
| HTML 结构变化导致解析失败 | 该源记为"解析失败"，不当作"查无此色"——**这两者含义相反，不能合并** |

**B. 色号库更新检查（开发/维护侧，不进运行时）**
- 落点：`scripts/update_paint_db.py`，手动执行。
- 行为：拉品牌目录 → 与本地 diff → 输出「新增 N 条 / 变更 M 条 / 待确认 K 条」→ 人工勾选入库。
- 不进运行时，就不存在超时降级和用户等待问题，也天然满足"人工确认才入库"。

### 3.4 若要做 A，涉及的模块

| 模块 | 职责 |
| --- | --- |
| **新增** `app/core/http_client.py` | 薄封装：超时、重试、并发上限、User-Agent。**必须放 core**——项目依赖方向铁律是 `ui → services → data → core`，反向导入禁止 |
| **新增** `app/data/verify_cache.py` | `userdata/cache/verify_cache.json`，key = `(brand, code)`，TTL 90 天（慢变数据），带 `verified_at` |
| **新增** `app/services/verify_service.py` | 编排：查询构造 → 多源并行 → 归一化 → 去重 → 排序 → 降级 |
| `app/ui/panels/suggestion_card.py` | 「核实」按钮 + 核实结果抽屉 |

**"检索过程可见"的正确落点**：核实抽屉里显示"查了哪几个源 / 各自耗时 / 各自状态（成功 / 超时 / 限流 / 解析失败）"。这才是用户真正需要看到的检索过程——不是把后台的 query rewrite 日志摊给用户。

> 依赖新增：`httpx`（或直接用标准库 `urllib`，省一个打包依赖，但并发与超时控制要自己写）。会**增加打包体积**，便携版目前 zip 约 54 MB。

### 3.5 联网效果的测试方式

用 monkeypatch 注入假 HTTP 层，覆盖：

- 正常多源 → 结果按 ΔE 排序、去重正确
- 单源超时 / 单源 429 / 单源返回乱码 → 其余源结果仍展示，失败源单独标注
- 全部失败 → **断言本地色号库数值逐位不变**（这是最关键的回归测试）
- 缓存命中 / 过期 / 文件损坏 → 损坏时静默降级为"未缓存"，不能崩
- 断言：请求体中**不含任何二进制字段**（隐私红线的自动化守卫）

---

## 4. 优先级与分期

| 期 | 内容 | 理由 |
| --- | --- | --- |
| **P0** | 数据契约 12 元组 + `sources.py` 注册表 + 8 元组兼容 + 自检反编造断言 | 一切溯源的基础，且纯数据层，不动 UI，风险最低 |
| **P1** | `provenance` 聚合 + UI 角标 / 置信度 chip / 可折叠来源区 + 替代色证据强度分级 | 用户可感知部分 |
| **P2** | 导出链路带来源（尤其分享文本） | 分享出去的东西最需要可追溯 |
| **P3** | 用量锚点来源标注 + 时效提示 | 数字类结论的置信度补齐 |
| **P4** | 联网核实（能力 A） | 前置依赖 P0，且需先确认隐私红线与开关设计 |
| **P5** | 库更新 diff（能力 B） | 维护侧工具，可长期缓做 |

P0–P3 是**纯离线**的，不引入任何新依赖、不破坏便携版特性。建议先做完 P0–P2 再回头评估 P4 是否真的需要。

---

## 5. 界面设计

配套交互稿见 `docs/mockup-provenance.html`（暗色主题，沿用 `app/ui/theme.py` 的 Palette 配色）。
