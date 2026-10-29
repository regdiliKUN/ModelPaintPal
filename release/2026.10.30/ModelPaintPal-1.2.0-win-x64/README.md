# ModelPaintPal · 3D 打印模型涂装配色助手

当前版本：**1.2.0**。本轮把配色搜索提速 **9.7×**（结果逐位不变），补上此前没有入口的
「配色方案」页（互补 / 三角 / 邻近 / 单色系等 7 种），并修掉一批边界与一致性问题
（空库被替换成全库、`max_results=0` 失效、溯源编号空号、安装脚本版本停留在 1.0.0 等）。
- [迭代记录](docs/ITERATION_2026-10-29.md)（43 轮，逐轮目标/改动/理由/自检）
- [性能优化说明](docs/OPTIMIZATION_2026-10-29.md)（只讲性能这条主线）

上一轮（1.1.0）修复的滴数与比例不一致、单色提示冲突、建议排序等问题见
[1.1.0 更新说明](docs/OPTIMIZATION_2026-10-25.md)。

一款 Windows 桌面应用：**从屏幕任意位置吸一个颜色 → 给出市面上真实可买的模型漆色号、
调配比例（滴数 / 百分比）、按喷涂面积估算的用量，以及买不到时的替代色号**。

面向 3D 打印件（PLA / 光敏树脂）涂装场景设计：默认考虑打印件未上水补土时"多吃漆"的
情况，并把整套工艺参数开放给用户按自己的喷笔习惯校准。

| 主界面 | 色卡对比 + 色盘 |
| --- | --- |
| ![主界面](docs/screenshots/01-main.png) | ![可视化](docs/screenshots/02-visual.png) |
| **用量参数** | **新手引导** |
| ![用量](docs/screenshots/03-coverage.png) | ![引导](docs/screenshots/04-onboarding.png) |

---

## 一、功能一览

### 1. 屏幕吸色
- **全局吸管**：任意窗口 / 图片 / 画布实时取色，放大镜逐像素定位（2×–40× 放大）
- **像素级精度**：进程级 Per-Monitor DPI 感知，125% / 150% 缩放下不偏移
- **数值显示**：HEX / RGB / HSV / CIELab 一屏展示，每项可一键复制
- **色差计算**：CIEDE2000（默认）/ CIE94 / CIE76 / CMC，并给出人眼可辨分级
- **历史记录**：自动滚动保存（可设上限），同色去重，点击色块可重新载入
- **收藏夹**：常用色固定留存，不参与历史淘汰
- **快捷键**：全局 `Ctrl+Shift+X` 开始吸色、`Ctrl+Shift+C` 复制色值（可在设置中修改）；
  窗口内 `Ctrl+1`–`Ctrl+5` 切换页签
- **调色微调**：在吸到的颜色上直接拖 色相 / 饱和度 / 明度 滑块试算"再亮一点能不能直接买到"，
  实时重算且不污染历史；一键还原原始取色

### 2. 配色建议
- **色号库**：672 条 / 11 个品牌 —— 田宫、郡士水性 H、郡士油性 C、AV Model Color、
  AV Model Air、AK 3rd Gen、AK Real Colors、AMMO by Mig、盖亚、Humbrol、SMS（与星影独立）
- **匹配**：Lab 空间最近邻搜索；ΔE 低于容差且为单色方案才标「可直接瓶用」，
  单色但色差偏大标「单色近似（色差偏大）」，其余标「需调配」
- **调色方案**：否则给出 2–3 色配方，颜色、ΔE、百分比与用量均以**实际整数滴数**为准；默认仅同一产品线混配，设置中可主动允许兼容性未验证的跨线混配
- **混合模型**：Kubelka-Munk 减色模型（默认）/ 线性光加权平均
- **预估用量**：按面积、层数、稀释比、施工方式、基材状态计算纯漆 / 稀释剂 / 混合液，
  折算"约几瓶"，多色配方再拆分到**每支漆各多少 ml**
- **快速套用**：1/35 战车 / 1/100 飞机 / 1/6 手办 三组面积·层数·基材预设
- **替代色号**：两条证据链 —— ① 同 FS/RAL/RLM/BS 标准色号；② 跨品牌 ΔE 最近色
- **导出与分享**：JSON / Markdown / CSV / TSV 四种文件导出；菜单「复制分享文本」一键生成
  可直接粘贴到群聊 / 论坛的纯文本配色卡（不带表格，任何客户端都不会错行）

### 3. 可视化与交互
- **ΔE 刻度尺**：按 1 / 2 / 3.5 / 5 分级画色带，指针落点直接告诉你"这个色差能不能接受"
- **色差对比**：目标色 / 混合结果左右分割预览 + 接缝白线；再把 Lab 差值放大 4 倍单独画一块，
  肉眼几乎看不见的偏色也能显形
- **色卡对比图**：目标色 / 混合结果 / 各组分 / 替代色并排，带 ①②③ 编号与每块 ΔE 角标，
  点击色块可复制色值；窄窗口自动换行
- **比例堆叠条形图**：段内单行标注「色号 · 滴数」，宽度不足自动省略
- **HSV 色盘**：一眼看出候选色偏在哪个方向；相近色号会自动错开并画引线指回真实位置，
  目标色带十字准星，编号与色卡一致
- **用量构成条**：纯漆 / 稀释剂的体积比例可视化
- **新手引导浮层**：4 步高亮讲解，可随时从菜单重看
- **工具提示**与**空状态说明**：空状态直接给出「开始吸色」按钮，错误当场显示原因

### 4. 基础配色（五瓶基础漆调配）
- **用途**：只要备齐 **红 / 黄 / 蓝 / 白 / 黑** 五瓶基础漆，就能调出吸到的任意目标色。
  不再是「每个基础色各给一瓶推荐漆」，而是把目标色**还原成这五瓶的混色配方**。
- **单条混色比例条**：一条堆叠条同时标出红、黄、蓝、白、黑各占 **百分之多少**，
  段内直接标注色号与**滴数**（如「红 60% / 12 滴」），一眼看清配比
- **滴数换算**：按设定总滴数（默认 20 滴）把百分比量化为整数滴，保证 Σ滴数 = 总量
- **品牌区分（重点）**：页签顶部有「基础漆品牌」下拉，**默认统一到单一品牌（田宫）**，
  把五瓶基础漆都推荐成同一个牌子的真实漆号（如田宫 X-7/X-8/X-4/XF-2/X-1），避免红用 AK、黄用郡士的杂乱。
  下拉里**每个品牌都能单选**（田宫 / 郡士水性H / 郡士油性C / AV / AK / AMMO / 盖亚 / Humbrol / SMS…），
  也提供「混搭（全部品牌）」回到各瓶可来自不同品牌；选中会落盘，下次启动沿用
- **跟随重算**：切换品牌、吸色、用量参数、数据库变化时自动重算；与左侧「建议范围」全局筛选相互独立
- **ΔE 提醒**：若目标色超出五瓶基础漆的还原能力（如高饱和绿），会显示预测色差，
  提醒你「靠这五瓶只能近似，差多少」
- **混合模型**：Kubelka-Munk 减色模型，在 K/S 空间对五瓶体积分数做最小二乘求解

---

## 二、快速开始

### 方式 A：直接用绿色便携版（推荐）
```
dist/ModelPaintPal-Portable.zip   →  解压到任意目录  →  双击 ModelPaintPal.exe
```
便携版目录下有 `portable.marker`，**所有用户数据（配置 / 历史 / 收藏 / 校准）都写在
程序同级的 `userdata\` 里**，整目录拷到 U 盘即可带走。
删掉 `portable.marker` 则改为写入 `%APPDATA%\ModelPaintPal`。

### 方式 B：从源码运行
```bash
pip install -r requirements.txt
python run.py
```

### 方式 C：自己打包
```bash
pip install -r requirements-dev.txt
python scripts/build.py                  # 绿色便携版 + zip
python scripts/build.py --mode onefile   # 单文件 exe
```
详见 [docs/BUILD.md](docs/BUILD.md)。

---

## 三、使用流程

1. **吸色**：点左侧「开始吸色」或按 `Ctrl+Shift+X` → 移动鼠标 → 左键取样（右键 / Esc 取消）
   - 也可以直接在输入框粘贴 `#RRGGBB` 或 `r,g,b` 后回车
2. **看建议**：右侧「配色建议」页按 ΔE 升序列出方案；ΔE 越小越接近
3. **复制配方**：卡片上「复制配方」/「复制 Markdown」，或菜单「文件 → 导出」
   （JSON / Markdown / CSV）；发群发帖用菜单「文件 → 复制分享文本」（`Ctrl+Alt+C`）
4. **调参数**：「用量参数」页改面积 / 层数 / 稀释比 / 施工方式 / 基材
5. **校准**：试喷后发现色值偏了 → 卡片上「校准色值」→ 输入你实测的 `#RRGGBB`
   （写入用户目录，不污染随包数据，可一键清除）

完整说明见 [docs/USER_GUIDE.md](docs/USER_GUIDE.md)。

---

## 四、项目结构

```
ModelPaintPal/
├── run.py                      开发入口
├── requirements.txt            运行时依赖
├── requirements-dev.txt        开发/构建依赖
├── installer.iss               Inno Setup 安装脚本（可选）
├── app/
│   ├── main.py                 应用引导（DPI / 日志 / 异常兜底）
│   ├── core/                   无 UI 依赖的基础层
│   │   ├── color_models.py     RGB/HEX/HSV/Lab 转换与格式化
│   │   ├── delta_e.py          CIE76 / CIE94 / CIEDE2000 / CMC
│   │   ├── screen_capture.py   mss 抓屏 + DPI 感知 + 光标/按键查询
│   │   ├── hotkeys.py          Windows 全局热键（RegisterHotKey）
│   │   ├── config.py           配置项（持久化 + 越界收敛）
│   │   ├── storage.py          JSON 原子写 + 损坏隔离
│   │   ├── paths.py            资源 / 用户目录解析
│   │   ├── sample_record.py    取色记录数据结构
│   │   ├── history_store.py    历史记录
│   │   ├── favorites_store.py  收藏夹
│   │   └── logging_setup.py    日志
│   ├── data/
│   │   ├── brands.py           品牌元数据（容量 / 稀释剂 / 漆基）
│   │   ├── paint_seed.py       色号种子数据（672 条）
│   │   └── paint_db.py         数据库构建 / 查询 / 校准覆盖
│   ├── services/
│   │   ├── mixing.py           Kubelka-Munk / 线性光混合模型
│   │   ├── recipe_engine.py    配方求解（1–3 组分，滴数换算）
│   │   ├── coverage.py         用量估算
│   │   ├── alternatives.py     替代色号检索
│   │   ├── paint_matcher.py    业务编排（核心）
│   │   ├── async_suggest.py    建议的线程池封装（吸色不卡界面）
│   │   └── export_service.py   剪贴板 / Markdown / JSON / CSV / TSV / 分享文本
│   └── ui/
│       ├── theme.py            暗色主题与 QSS（标签角色 Chip/Hint/Error 等）
│       ├── paint.py            自绘控件的 QPainter 上下文（必定 end）
│       ├── presenters.py       建议 → 色卡/色盘/图例的视图模型（编号唯一来源）
│       ├── main_window.py      主窗口
│       ├── onboarding.py       新手引导浮层
│       ├── picker/             放大镜窗口 + 吸色控制器
│       ├── widgets/            色卡 / 比例条 / 色盘 / 数值 / Toast / 空状态
│       └── panels/             取色 / 建议 / 可视化 / 用量 / 设置 / 历史收藏
├── scripts/
│   ├── build.py                打包脚本
│   ├── smoke_test.py           离屏端到端冒烟
│   ├── check_paint_db.py       色号库自检
│   ├── bench.py                性能基准（delta_e / suggest）
│   ├── quality_metrics.py      代码质量与渲染耗时度量（迭代前后对比用）
│   └── screenshot.py           离屏渲染 10 张界面截图（视觉回归）
├── tests/                      307 项自动化测试（不依赖显示器）
│   ├── test_color_math.py      颜色转换 / 解析 / 往返精度 / 混合 / 配方
│   ├── test_delta_e.py         CIEDE2000 与 Sharma 论文基准值对表
│   ├── test_config.py          配置逐字段容错 + 字段名守卫 + 恢复默认
│   ├── test_storage.py         原子写 / 损坏隔离 / 脏数据过滤 / 上限裁剪
│   ├── test_sample_record.py   历史记录脏数据健壮性 + 序列化往返
│   ├── test_screen_capture.py  屏幕边缘取色夹取 + 块平均
│   ├── test_matcher.py         配方 / 替代色 / 用量 / 导出 / 模糊测试
│   ├── test_paint_db.py        色号库检索 / 品牌 / 可混色判定
│   ├── test_data_integrity.py  品牌元数据 + 种子色号表体检
│   ├── test_paths.py           路径工具
│   ├── test_logging.py         日志初始化幂等
│   ├── test_async_suggest.py   离线程结果与同步结果一致性
│   └── test_ui_smoke.py        主窗口冒烟（offscreen）
└── docs/
    ├── DATA_ITERATIONS.md      资料检索 22 轮迭代记录
    ├── REFACTOR_LOG.md         重构优化 24 轮记录
    ├── ITERATION_LOG.md        质量迭代 25 轮记录（正确性/边界/性能）
    ├── BUILD.md                构建与发布
    └── USER_GUIDE.md           用户手册
```

依赖方向严格自上而下：`ui → services → data → core`，反向导入一律禁止。

---

## 五、算法与模型说明

### 色差
默认 **CIEDE2000**（工业标准，对蓝紫区与近中性灰修正最好）。分级阈值：

| ΔE2000 | 判定 |
| --- | --- |
| < 1.0 | 肉眼几乎无法分辨 |
| 1.0 – 2.0 | 极接近，仅并排对比可察觉 |
| 2.0 – 3.5 | 近距离可见差异，喷涂可接受 |
| 3.5 – 5.0 | 明显不同，需接受色偏 |
| > 5.0 | 完全不同的两个颜色 |

### 混合模型
- **Kubelka-Munk（默认）**：RGB三通道近似，作为不透明漆试喷的起点，不等同于使用实测光谱的物理模型
- **线性光加权平均**：用于数字颜色对比，不保证实漆或透明漆叠加准确度

两者都在线性光空间计算，避免伽马偏差。

### 用量估算
```
原漆   = 面积 × 层数 × 原漆单位用量 × 施工损耗 × 基材系数 × 余量 + 固定原漆损耗
稀释剂 = 原漆 × 稀释比
混合液 = 原漆 + 稀释剂
```
原漆基准默认 **55 ml/m²/层**，仅为保留旧版参考1:1稀释时估算的迁移约定，
**不是模型漆实喷数据，也不再引用汽车工艺资料作为该数值的换算证明**。请按个人喷笔习惯校准。
为兼容旧配置，`mix_ml_per_m2_per_coat`键继续保存该原漆基准的2倍，界面直接显示原漆基准。
固定损耗默认0，按每次调漆单独计入；预稀释产品默认不再额外加稀释剂，可在用量页关闭自动模式。

- 施工损耗：喷笔 1.35× / 笔涂 1.05× / 喷罐 1.60×
- 基材系数：已上补土 1.00 / **3D 打印件未处理 1.30** / 光面塑料 1.10
- 遮盖力弱的色系（黄 / 橙 / 荧光）自动 +1 层

---

## 六、重要声明（请务必阅读）

1. **色值是近似值**。来源是官方色卡的屏幕取色与标准色（FS / RAL / RLM / BS）的公开
   色度数据，用于**相对匹配与配比估算**，不等于实干漆膜。不同批次漆、底材、光泽、
   膜厚都会造成偏差。请用「校准色值」功能用你的试喷结果反哺。
2. **正式喷涂前务必小量试喷**。尤其是跨品牌混用（不同漆基相容性不同）。
3. **3D 打印件建议先上水补土**。层纹会显著增加吃漆量，也会让颜色看起来更深。
4. **消光保护漆会让颜色看起来变浅/泛白**，光泽保护漆则更饱和更深 —— 评估颜色时
   请在最终光泽状态下判断。

资料检索与交叉校验的完整过程见 [docs/DATA_ITERATIONS.md](docs/DATA_ITERATIONS.md)。

---

## 七、开发

```bash
python -m pyflakes app scripts tests run.py   # 静态检查（应无输出）
python -m unittest discover -s tests          # 单元测试（307 项，全部离屏）
python scripts/smoke_test.py                  # 离屏端到端冒烟
python scripts/check_paint_db.py              # 色号库自检
python scripts/bench.py                        # 性能基准（delta_e / suggest）
python scripts/quality_metrics.py             # 代码质量 / 渲染耗时度量
python scripts/screenshot.py                   # 离屏截图（改动界面后逐张核对）
```

测试与静态检查是每次改动的门禁：`pyflakes` 无输出、`unittest` 全绿、冒烟 12 项全 PASS
才算通过。质量迭代的逐轮记录见 [docs/ITERATION_LOG.md](docs/ITERATION_LOG.md)，
第三轮（UX / 可视化 / 代码质量，35 轮）见 [docs/ITERATION_R3.md](docs/ITERATION_R3.md)。

---

## 八、运行环境

- Windows 10 1607+ / Windows 11（x64）
- 无需管理员权限（热键走 `RegisterHotKey`，吸色用轮询而非全局鼠标钩子）
- 打包体积：便携版目录约 130 MB，zip 约 54 MB

## 九、许可

MIT，见 [LICENSE](LICENSE)。
