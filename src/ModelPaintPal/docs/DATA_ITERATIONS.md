# 模型漆色号资料：检索与交叉校验迭代记录

> 目标：为「屏幕吸色 → 给出现实可买的漆种、配比、用量、替代色号」建立一份
> **可追溯、可校验、可校准**的色号资料库。
> 本文记录 22 轮迭代：第 1–14 轮为联网检索与交叉比对，第 15–22 轮为数据工程
> （结构规范化、冲突消解、覆盖率提升、可校验化）。

最终规模：**672 条色号 / 11 个品牌 / 79 个标准色号**，其中 186 条直接挂载了
FS / RAL / RLM / BS 标准色号，32 个标准色号可实现跨品牌互换推荐。

---

## 第 1 轮 — 郡士（Mr.Hobby）水性 H 系列色号表

- 检索词：`郡士 Mr.Hobby 水性漆 色号表 H系列 色卡 Aqueous Hobby Color 完整色号`
- 主要来源：HRS 模型（H-1 ~ H-151 中文名对照）、TwinnerModel 英文名录、
  GSI Creos 官网产品页、manuals.plus 的 Mr.Hobby 产品目录
- 收获：确认 H 系列命名规则（H-1 白 / H-2 黑 / H-11 消光白 / H-12 消光黑 …）
  与军事色段（H-64~H-70 对应 RLM 71/70/79/65/74/75/02）
- 冲突处理：manuals.plus 的摘录把 H1/H2 写成「H1 Black, H2 White」，与官方
  「H-1 White / H-2 Black」相反 → **以 GSI 官方与两家零售目录为准**，驳回该来源

## 第 2 轮 — 田宫（Tamiya）X / XF 色号表

- 检索词：`田宫 Tamiya 模型漆 X XF 色号表 色卡 对照 列表`
- 主要来源：Tamiya 官网 Acrylic / Enamel 产品列表、搜狗百科「田宫漆表」、
  Tamiya HK 套件涂装表（含 TS/AS 喷罐对照）
- 收获：补齐 XF-49 ~ XF-85 的中文名（消光卡其、北约迷彩三色、橡胶黑等）
- 交叉校验：X-32 Titanium Silver 的十六进制值在第三方色卡站（paint-vault）
  给出 `#CDCCB8`，与本库取值一致 → 采纳

## 第 3 轮 — Vallejo Model Color（70.xxx）

- 检索词：`Vallejo Model Color 色号表 70.8xx 色卡 名称 列表`
- 主要来源：Acrylicos Vallejo 官网 Basic Case 目录、The Outpost / Popstop 目录
- 收获：确认 70.951 白、70.950 黑、70.919 Foundation White 等主力色，
  以及 70.887 US Olive Drab、70.921 English Uniform 等军事色的标准色号归属
- 处理：不同批次套装的色号→名称映射存在差异（例如 71.003 在旧套装叫
  Scarlet Red、新套装叫 Red RLM23）→ **以官网最新 Color Selection 目录为准**

## 第 4 轮 — 调色与稀释工艺（配方表达形式的依据）

- 检索词：`模型漆 调色 配方 混合比例 滴数 稀释比例 喷涂 教程`
- 主要来源：巴哈姆特模型技术板涂装实录、堤業國際 TB 水漆喷塗示範
- 收获：**行业习惯用「滴数」表达配比**（如 5 滴漆 : 2 滴水，10 滴 A + 20 滴 B），
  因此本应用把比例同时输出为「滴数」和「百分比」两种形式；
  同时确认喷笔常用稀释比为 1:1 ~ 1:2（漆:稀释剂）

## 第 5 轮 — AK Interactive 3rd Generation（AK11xxx）

- 检索词：`AK Interactive 3rd Generation Acrylic 色号 色卡 名称 列表 AK11000`
- 主要来源：ak-interactive.com 产品页、diecastmates 色域表、mech9 色卡表
- 收获：确认 AK11001 起为灰阶、AK11030 起沙土、AK11044 起黄、AK11085 起红
  的分段规律，补齐 78 条主力色

## 第 6 轮 — AMMO by Mig Jimenez（A.MIG-0xxx）与官方转换表

- 检索词：`AMMO by Mig Jimenez 模型漆 A.MIG 色号 色卡 列表`
- 主要来源：migjimenez.com 官方 **Acrylic Colors Conversion Chart (PDF)**、
  Scale Model Scenery 目录、SprayGunner 科幻套装说明
- 关键收获：官方转换表同时给出 `ATOM / A.MIG / Mr.Hobby H / Mr.Color C /
  Tamiya XF / Vallejo / FS / RAL / RLM` 的对应关系 →
  **本应用「替代色号」功能的两条证据链之一（同标准色号）即以此为依据**
- 备注：PDF 站点有 Cloudflare 拦截，改用搜索引擎抓取的正文片段做交叉核对

## 第 7 轮 — Gaia Notes（盖亚）

- 检索词：`Gaia Notes 盖亚 模型漆 色号 色卡 列表 ガイアノーツ`
- 主要来源：gaianotesna.com 官网产品线页、eBay / HobbyDigi 色号目录
- 收获：确认基本色（001-049）、中性灰 I~V（071-075）、荧光（102-110）、
  星辉金属（121-126）、珠光（131-133）与军色（201-221）分段；
  061/062 分别对应 FS15042 / FS35164

## 第 8 轮 — 标准色号体系（FS595 / RAL / RLM / BS381C）

- 检索词：`FS595 RAL RLM 色值 RGB 对照表 军事标准色 模型`
- 主要来源：cuscolor 的 Federal Standard 595 Paint Spec（含 hex 表）、
  rcmates / papermates 色片库、Wikipedia FS595 迷彩色条目
- 收获：确认 FS 编码语义（首位 1/2/3 = 光泽/半光/消光，次位为色系），
  并取到 FS14241 `#87A298`、FS24031 `#575450`、FS16376 `#A9A99E` 等锚点值
- 交叉校验：papermates 与 rcmates 对同一 FS 号给出的 RGB 在 ±3 内 → 采信

## 第 9 轮 — 数字化色值来源（paint-vault / paintatlas）

- 检索词：`model paint hex color chart database tamiya vallejo mr hobby RGB values json dataset`
- 主要来源：paintatlas.com（Vallejo 71.003 `#C71F1C`、71.106 `#C8B269`）、
  paint-vault.com（Tamiya 81010 Gun Metal `#4F5457`、80032 Titanium Silver `#CDCCB8`）
- 收获：这两个站直接给出 HEX + CIELAB，是**校正本库近似色值的重要参照**；
  本库多处以它们的取值替换了原先的估算值
- 冲突处理：paint4models 的 Ultimate Conversion Chart（PDF）无法直接抓取，
  改用其搜索引擎正文片段里的 FS↔hex↔品牌对照做补充核对

## 第 10 轮 — 3D 打印件涂装前处理（本应用的目标场景）

- 检索词：`3D打印模型 涂装 流程 水补土 底漆 PLA 树脂 喷涂 稀释 比例`
- 主要来源：福州 3D 打印后处理工艺文、创想云打磨喷涂帖、
  郡士水补土喷涂教程、百度爱采购水补土稀释比例词条
- 收获：PLA 需 320→1000 目逐级打磨；树脂件需二次固化 + 异丙醇清洗；
  水补土常用稀释比 1:2（细节件 1:3）；面漆喷笔参数 1:1.5~1:2、15~20 PSI
- 落地：这些数字成为「用量估算」里 `raw_print` 基材系数 1.30 与
  默认层数建议的依据

## 第 11 轮 — 单位面积用量的量化锚点

- 检索词：`模型漆 用量 估算 每毫升 喷涂面积 覆盖率 稀释 1:1 喷笔`
- 主要来源：TailorMadeDecals 的《Processing of base coats, primers, and clear coats》
  （汽车底色漆 **100–150 ml 未稀释材料 / 1 m²**）、Tamiya 喷罐说明
  （100 ml 可喷完 2~3 个 1/48 飞机）
- 落地：把「已稀释混合液 110 ml/m²/层」设为默认基准参数，并在设置里开放校准

## 第 12 轮 — 色差阈值与公式选型

- 检索词：`色差 ΔE 阈值 人眼 辨别 CIE76 CIEDE2000 ΔE<1 不可见 2-3 明显 标准`
- 主要来源：ScienceInsights、colorfyi、ViewSonic、Tampere 大学柔性印刷论文
- 结论：JND ≈ ΔE 1.0；ΔE ≤ 2 为多数行业可接受容差；
  ISO 12647-7 对合同打样要求 ≤ 2.5 ΔE2000
- 落地：**默认使用 CIEDE2000**，同时保留 CIE76/94/CMC 供切换；
  ΔE 分级文案按「<1 无法分辨 / 1-2 极接近 / 2-3.5 可见 / 3.5-5 明显 / >5 完全不同」输出

## 第 13 轮 — 国产品牌与预稀释漆（星影 / SMS）

- 检索词：`星影模型漆 SMS 国产 模型漆 品牌 色号 色卡`
- 主要来源：SMS（The Scale Modellers Supply）官方经销页、
  Lumins Workshop 的 SMS Infinite Colour 目录、台湾露天星影 X 系列目录、
  湖州星影军模色目录
- 收获：SMS 为**预稀释**漆（免稀释直喷），因此其稀释比应填 0；
  星影 X/J/JXF 系列沿用田宫色号命名（JXF-67/68/69 对应北约迷彩三色）

## 第 14 轮 — 光泽对呈色的影响

- 检索词：`消光 半光泽 光泽 清漆 对颜色 明度 饱和度 影响 模型`
- 主要来源：登王水性涂料《表面光泽如何影响样品的颜色和外观》、
  网易「模型学园」保护漆横向评测、Mr.Joe 保护漆教程
- 结论：光泽面镜面反射强 → 看起来更饱和更深；消光面漫反射 → 看起来更浅更灰；
  同一漆喷消光保护漆后普遍「变亮/泛白」
- 落地：色号数据保留 `finish` 字段，UI 明确提示「实干漆膜会因光泽与膜厚产生偏移」；
  不做数值补偿（避免引入不可验证的偏差），改由用户校准

---

## 第 15 轮 — 统一数据契约

把 11 个品牌各自不同的目录格式统一为 8 元组：

```
(code, 中文名, 英文名, hex, finish, opacity, standards, note)
```

- `finish`：gloss / semi / flat / metal / pearl / clear / fluor
- `opacity`：opaque / semi / clear（决定建议层数是否 +1）
- `standards`：FS / RAL / RLM / BS / 4BO / 7K，多个用 `;` 分隔

## 第 16 轮 — 建立可执行的自检脚本

新增 `scripts/check_paint_db.py`，把「人工翻目录」变成自动化断言：

- 字段数、hex 正则、finish/opacity 取值域
- 同品牌内色号重复
- 品牌必须在 `brands.py` 中存在
- 统计标准色号覆盖率与跨品牌可互换标准色数量

运行结果：`色号库自检通过`（672 条 / 11 品牌 / 186 条带标准色号 / 32 个可跨品牌互换）

## 第 17 轮 — 冲突消解：同一色号多名

- 71.003：旧目录「Scarlet Red」vs 新目录「Red RLM23」→ 采用官网最新目录
- RC013：官方「Off White」vs 零售端「米白」→ 中英文名分列，保留两种叫法
- H-95 / C-101 / X-19：透明烟色归入 `clear`，并在匹配时默认排除（见第 19 轮）

## 第 18 轮 — 品牌元数据补全

新增 `brands.py`，为每个品牌补齐：产品线、漆基类型（水性丙烯酸 / 硝基 / 珐琅）、
单瓶容量、推荐稀释剂、产地、官网。容量直接用于「约几瓶漆」的换算，
稀释剂文案直接进配方提示。

## 第 19 轮 — 可调和性分层

验证：透明漆（clear）与荧光漆（fluor）的混合行为与不透明漆完全不同，
把它们混进配方会给出错误建议。

处理：新增 `PaintEntry.is_mixable()`，默认排除 clear / fluor / metal / pearl，
并在设置里提供 `allow_metallic_in_mix`、`allow_clear_in_mix` 两个开关。
自检结果：tamiya 63 / mr_color_c 72 / gaia 35 条可参与调配（金属与荧光占比高
的品牌可调和条目明显更少，符合预期）。

## 第 20 轮 — 覆盖率检查

按品牌统计「极浅色（L*>88）」与「极深色（L*<20）」的数量，确认每个品牌都
至少有提亮用白和压暗用黑 —— 否则该品牌的配方搜索会缺失两个最基本的调节手段。

结果：11 个品牌全部具备（white 1~5 条、black 1~5 条），通过。

## 第 21 轮 — 校准回路（把误差交还给用户）

承认：屏幕近似色值 ≠ 实干漆膜。与其假装精确，不如让用户用试喷结果反哺。

实现：
- `app/data/paint_db.py::calibrate(uid, hex)` 把用户实测值写入
  `user_overrides.json`（存放在用户目录，**永不污染随包数据**）
- 写入后立即重建数据库并刷新界面
- 设置页展示当前校准清单，支持一键清除

## 第 22 轮 — 可追溯性收尾

- 每条色号在 UI 上都能显示来源品牌、漆基、光泽、遮盖力
- 文档明确写出「色值用于**相对匹配**，正式喷涂请先试喷」
- 用量估算把模型公式与锚点来源写进界面提示，参数全部开放可调

---

## 已知局限（不掩饰）

1. **色值是近似值**：来源是官方色卡的屏幕取色与标准色的公开色度数据，
   不同批次漆、不同底材、不同光泽都会造成偏差。请用「校准」功能修正。
2. **混合模型是三频段近似**：Kubelka-Munk 只用 RGB 三个波段，对互补色混合
   会偏保守（比真实颜料更暗）。设置里可切换 `linear_rgb` 对比。
3. **替代色号的同标准判定依赖各品牌自己的标注**，部分品牌的标注并不严谨。
4. 用量估算的锚点来自汽车底色漆工艺数据，模型漆膜更薄，默认值 110 ml/m²/层
   建议按个人喷笔习惯校准。
