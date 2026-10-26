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
  theme.py          # 移动端主题
  app.py            # Kivy App + 底部导航
  widgets/          # 通用控件 + 建议卡片 / 混色比例条 / 色卡网格
  screens/          # 各功能页
  main.py           # 入口
  tests/            # 测试
```

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

> 说明：当前开发沙箱没有 Java / Android SDK，无法在此编译 `.apk`；上面的 app 代码已在桌面端
> 跑通并通过逻辑测试，按上述命令在装有工具链的机器上即可出包。

## 测试
```bash
python -m unittest discover -s mobile/tests -p "test_*.py" -v
```
- `test_mobile_logic.py`：核心移植功能（建议 / 调配 / 覆盖率 / 收藏 / 导出 / 校准），无需图形界面即可运行。
- `test_mobile_ui.py`：界面冒烟（在无显示环境会自动跳过，在有图形界面的机器 / CI 上运行）。
