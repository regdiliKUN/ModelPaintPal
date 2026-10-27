# ModelPaintPal 移动端（Android APK）

把桌面端「3D 打印模型涂装配色助手」完整移植到 Android。UI 为移动端重设计，
**全部核心逻辑（配色引擎 / 色差 / 配方 / 漆库 / 覆盖率）直接复用桌面端的纯 Python 代码**，
只重写了展示层（Kivy）。

## 功能（与桌面端一一对应）
- **取色**：从手机图库选择照片后**进入全屏取色层**——整块屏幕就是取色板，按住即取色、拖动实时跟随、松手确认；屏幕顶部有 6× 放大图 + 准星 + 色块 + HEX，能看清正在取哪个像素（放在顶部是为了不被自己的手指挡住）。也支持手动输入 HEX / RGB 滑块。
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
  photo.py          # 选图 + 照片载入（Android Intent/ContentResolver，桌面 tkinter）
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
7. **选图不要用 `plyer.filechooser`**。它 Android 端只做 `intent.getData().getPath()`，
   对 `content://media/...` 这类 URI 返回的是假路径（如 `/document/image:1234`），
   PIL 打不开 —— 现象就是「在相册里选好照片并确认后，界面上什么都没出现」。
   统一走 `photo.pick_image()`：自己发 Intent，用 `ContentResolver` 读字节，
   顺带处理 EXIF 旋转、超大图缩放、缓存清理。
8. **图片区用 `FloatLayout` 且子控件必须给 `pos_hint`**。`FloatLayout` 不会给没有
   `pos_hint` 的子控件定位（会停在窗口原点 `(0,0)`）；而 `RelativeLayout` 里子控件的
   `pos` 是 0~1 的相对单位，拿去算屏幕坐标会得到 `y=0` 这种结果。
9. **换算屏幕坐标一律用 `widget.to_window(x, y)`**，不要直接拿 `pos` 加偏移：
   控件在 ScrollView 里时 `pos` 只是内容区内的局部值，实测和窗口坐标差 1000px 以上，
   会让吸色整体偏移（手指点红色取到别的颜色）。
10. **不要在运行时改「卡片里某个固定高度子控件」的高度**。实测把取色区从 170dp
    拉到 280dp 会触发重排，把同一张卡里的按钮宽度压成 26px（正常 1328px）。
    需要多大就在建的时候定好。
11. **Toast 不要用 `ModalView` 实现**。它默认带一层 70% 黑遮罩（弹一次提示整个界面
    暗一下），还会干扰后续绘制。`app.toast()` 已经把浮层直接挂到 `Window` 上。
12. **读图/解码/缩放不能放主线程**。手机相册里一张 12MP 照片走
    「ContentResolver 读字节 → `Image.open` → EXIF 摆正 → 缩到 2560 → 存 PNG」
    在低端机上是 1~3 秒，卡在主线程既有明显冻结，也可能触发系统 ANR。
    `photo.py` 用后台线程做这一段，结果再经 `Clock.schedule_once` 切回主线程回调。
13. **取色区必须放在「铺满窗口的独立层」里，只用 `touch.pos - self.pos`。**
    这一条踩了三次，前两次都是在「算准」触摸与绘制之间的换算关系，实机上
    全都整体偏下几百像素：
    - `touch.pos` 在 ScrollView 里会被 `g_translate` 平移一次，更要命的是
      **按下走控件树、拖动和抬手走 `Window` 事件**，两条路的坐标系不同 ——
      同一手指位置实测按下读 1180、拖动读 1886，差 706px。
    - `self.pos` 是父容器坐标，和屏幕上画的位置隔着整条布局链（实测
      `self.pos=(28,731)`，照片却画在 `(56,1277)`）；页面一滚动差得更多。
    - 用 `touch.sx/sy` 还原窗口坐标 + `get_window_matrix()` 还原控件原点，
      这套在桌面逐像素验证全对（静止、滚动、拖动都验过），**真机仍然偏**。
      既然推导链上还有环境相关的量收不干净，就别推导了。
    现在的做法：取色区是 `PickOverlay(ModalView)` —— 铺满窗口、`pos=(0,0)`、
    `size=Window.size`，照片区再放进它内部的 BoxLayout。于是
    **父容器坐标 == 窗口坐标**，`touch.pos - self.pos` 就是 canvas 用的局部
    坐标，按下 / 拖动 / 抬手三条路给出同一套值，不依赖任何矩阵推算。
    验证脚本 `_shots/verify_overlay.py`：真实触摸派发 + 截图四角标记，
    四个象限全部 `取样色 == 截图像素 == 期望色`。

14. **`Line` 在这个环境里画不出来**。`Line(circle=...)`、`Line(points=...)`
    放在图片上/旁边一律不渲染，而且 `Line.circle` 只可写不可读（读回 `None`，
    没法用它做状态判断）。要图形就用 `ColorRect`，或干脆用 PIL 画进图片
    再 `Image(source=文件)`。
15. **照片这个 `Image` 会盖住同层级的所有控件**：holder 里的兄弟控件、
    它自己的子控件，全部被照片盖掉（用四色探针逐个验证，只有一个能露出来）。
    所以「准星、十字线、坐标浮层」这类叠加物**不要往照片上放**——
    `pick_screen` 的做法是把准星画进照片下方的放大图里。
16. **`opacity = 0` 拨一次就永久破坏该控件的绘制**，之后即使拨回 1 也不再画。
    藏东西请改用：清空 `text`、移出父容器、或换成透明占位图。
17. **`Image` 没有 `source` 会画成一块纯白方块**。占位统一用 `blank_png()`
    （`cache_dir()/blank.png`，2×2 全透明）。
18. **细长条不要设圆角**。圆角半径大于控件半高时会退化成空几何，整条消失
    （`Slider` 的轨道、分隔线尤其容易踩）。
19. **同名文件换图必须 `nocache=True` + 原子落盘**。Kivy 会对 `source`
    做 `kv.loader`/`kv.texture` 缓存，重写同名文件后画面还停在第一帧
    （放大图看起来「不动」）。写法：先存 `.tmp`，再 `os.replace()` 到目标名，
    已加载同名路径时调 `reload()`。
20. **`Window.screenshot()` 的坑（做截图校验前务必看）**：
    - 文件名会自动追加 `{:04d}` 序号，别用「文件名等于我传的」去判断；
    - 它读的是**已经渲染完的 framebuffer**，窗口在后台/被遮挡时可能连续
      好几拍都返回**同一张旧画面** —— 实测连拍 5 张（间隔 0.12s）都是「按下前」
      的界面，而同一时刻控件状态早已更新（HEX 已从 `#000000` 变成 `#FFF000`）。
      于是断言「屏幕上有没有画出来」会得到假的失败结论。
    - **可靠性排序**：直接读落盘图片（如 `zoom.png`）+ 检查 `widget.texture`
      ≫ 截图。确需截图时把窗口切到前台，并在同一个 tick 内先截图再读像素。
21. **Kivy 会吞掉 stdout**。无头环境写测试报告要自己 `open(..., 'w')` 落盘，
    不能指望 `print` 出现在终端里。

22. **这个 Kivy 构建里 `touch.grab_current` 永远是 `None`**。`grab()` 只往
    `grab_list` 里追加，从不更新 `grab_current`（实测：`grab_list` 长度为 1
    而 `grab_current` 是 None）。所以官方文档那套
    `if touch.grab_current is self:` 在这里会让**拖动和抬手全部失效** ——
    表现就是「按下去有反应、一动就不动了」/「松手没取到色」。
    判断「是不是我按下的那根手指」要用**对象身份**：
    `if self._touch is None or touch is not self._touch: return False`。

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
- `test_mobile_photo.py`：选图与吸色回归（字节→照片→界面整链路、EXIF 摆正、
  缓存清理、`contain` 居中留白的坐标映射、按下即取样 / 拖动跟手 / 抬手只提交一次、
  放大图中心必须就是取到的那个像素、留白处夹取不报错、**全屏取色层铺满窗口**、
  **坐标系**：取色区放在 `pos=(0,120)` 时仍要取对颜色、拖动与按下必须是同一套坐标）。
- 无头环境跑 UI 测试需指定窗口后端：`KIVY_WINDOW=sdl2 python -m unittest ...`，
  否则 Kivy 在 import 阶段会静默崩溃。
- 注意用 `discover` 形式运行：`python -m unittest discover -s src/ModelPaintPal/mobile/tests -t src`。
  直接 `-m unittest 模块名` 在本机会因 Kivy 的 stdout 代理而**一行输出都没有**。
