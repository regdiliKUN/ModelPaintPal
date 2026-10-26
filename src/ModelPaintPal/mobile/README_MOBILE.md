# ModelPaintPal 移动端（Android APK）

把桌面端「3D 打印模型涂装配色助手」完整移植到 Android。UI 为移动端重设计，
**全部核心逻辑（配色引擎 / 色差 / 配方 / 漆库 / 覆盖率）直接复用桌面端的纯 Python 代码**，
只重写了展示层（Kivy）。

## 功能（与桌面端一一对应）
- **取色**：从手机图库选择照片，**长按照片任意位置吸色**；也支持手动输入 HEX / RGB 滑块。
- **配色建议**：按 CIEDE2000 等色差公式给出最接近的漆（11 品牌库），含配方、覆盖率、替代色。
- **色卡对比**：目标色与候选漆并列，点按复制色值。
- **基础漆调配**：把任意目标色分解为红 / 黄 / 蓝 / 白 / 黑五瓶基础漆的配比（同一条混色比例条 + 滴数），并可指定基础漆品牌。
- **用量估算**：面积 / 层数 / 稀释比 / 工具 / 表面 → 用漆量估算。
- **收藏 / 历史**：取过的颜色可收藏、历史可回溯、可删除。
- **设置**：匹配容差、建议条数、配方组分数、调色模型等。
- **校准 / 联网核实**：可对漆号校准实测色值，或联网核实官方色卡。

## 目录结构
```
mobile/
  bootstrap.py      # 路径重定向：把用户数据写到 Android 可写目录
  logic.py          # 逻辑胶水层（复用 core/data/services，线程计算 + Kivy 剪贴板）
  theme.py          # 主题：配色 + D()/S() 尺寸换算
  fonts.py          # 中文字体注册（内置 Noto Sans SC，逐级回退系统字体）
  assets/fonts/     # 随包字体（打 APK 时一并打包）
  app.py            # Kivy App + 底部导航
  widgets/          # 通用控件 + 建议卡片 / 混色比例条 / 色卡网格
  screens/          # 各功能页
  main.py           # 入口
  tests/            # 测试
```

## 移动端适配约定（重要，改 UI 前先看）
1. **所有尺寸必须用 `D(x)`（dp）和 `S(x)`（sp）换算**，不能直接写像素数字。
   高密度屏（1080p，density≈2.75）上写死的 `48` 只有约 17dp，整页会被压成顶部一条。
   `S()` 还处理了「窗口未就绪时 Kivy `fontscale` 为 -1」的坑，避免出现负字号。
2. **滚动容器里的卡片必须自适应高度**（`size_hint_y=None` + `minimum_height`）。
   `Card` 已内置；若子控件 `size_hint_y` 为默认值 1，`BoxLayout.minimum_height` 会算成 0，
   整页高度塌陷（这也是"打开后只剩一条"的元凶之一）。
3. **中文字体必须注册**。Kivy 默认 Roboto 不含中日韩字形，不注册就是一片方框。
   `fonts.py` 会把内置字体同时注册为 `MppCJK` 并覆盖默认 `Roboto`，
   因此 Spinner / TextInput 等系统控件也自动生效。
4. **不要在绑定回调里 `canvas.clear()` 重建绘图指令**，会破坏 Kivy 渲染上下文栈，
   触发 `RenderContext.pop_state` 的 `IndexError` 崩溃。绘图指令只建一次，之后只改属性。
5. **带 `suggestion=` 等初值构造的控件要在 `__init__` 末尾主动渲染一次**，
   因为 Kivy 的 `bind` 在构造末尾才建立，初始值不会触发回调（否则卡片是空的）。
6. 触控目标不小于 48dp；底部导航高度 `D(56)`。

## 本地桌面调试
```bash
pip install kivy pillow plyer
python mobile/main.py
```

## 打包 APK（需要 Android 工具链）
本机（开发机）需先安装：
- Java JDK 17
- Android SDK（cmdline-tools）+ NDK r25b
- Buildozer：`pip install buildozer`

然后在仓库根目录执行：
```bash
buildozer android debug        # 生成 bin/ModelPaintPal-1.1.0-debug.apk
buildozer android release      # 签名发布版（需先配置 keystore）
```

> `buildozer.spec` 的 `source.include_exts` 已包含 `otf`，确保内置中文字体被打进 APK；
> `android.permissions` 已包含 `READ_MEDIA_IMAGES`（Android 13+ 选图需要）。

## 测试
```bash
python -m unittest discover -s mobile/tests -p "test_*.py" -v
```
- `test_mobile_logic.py`：核心移植功能（建议 / 调配 / 覆盖率 / 收藏 / 导出 / 校准），无需图形界面即可运行。
- `test_mobile_ui.py`：界面冒烟 + **适配回归**（字号必须按 sp 缩放、卡片高度不能塌陷、
  导航满足 48dp 触摸目标）。
- 无头环境跑 UI 测试需指定窗口后端：`KIVY_WINDOW=sdl2 python -m unittest ...`，
  否则 Kivy 在 import 阶段会静默崩溃。
