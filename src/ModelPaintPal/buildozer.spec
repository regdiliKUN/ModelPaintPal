[app]

# (str) 应用标题
title = ModelPaintPal

# (str) 包名
package.name = modelpaintpal

# (str) 包域（影响 Android 应用 ID）
package.domain = org.kivy

# (str) 源码目录（含 app 核心库与 mobile 前端）
source.dir = .

# (list) 需要打包的扩展名
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,db,ttf,txt,md,csv

# (list) 排除目录：测试 / 构建产物 / 桌面端 PySide6 UI / 文档
source.exclude_dirs = tests,build,dist,docs,scripts,.git,app/ui,app/resources

# (str) 入口文件（位于 source.dir 根）
source.main = main.py

# (str) 版本
version = 1.1.0

# (list) 依赖（python3 由 p4a 自动加）
requirements = python3,kivy,pillow,plyer

# (str) 应用方向
orientation = portrait

# (list) Android 权限：联网核实需要 INTERNET；选相册照片需要读媒体权限
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,READ_MEDIA_IMAGES

# (int) Android API / 最低 API / NDK
android.api = 33
android.minapi = 21
android.ndk = 25b
android.sdk = 33
android.buildozer_version = 1.5.0

# (bool) 私有存储（用户数据写入 App 私有目录）
android.private_storage = True

# (bool) 自动接受 SDK 许可：CI 无人值守构建必须开启，否则会卡在交互提示
android.accept_sdk_license = True

# (list) 目标架构：只编 arm64-v8a（现代手机均支持），构建时间约减半
# 需要兼容老机型时改成：arm64-v8a, armeabi-v7a
android.archs = arm64-v8a

# (str) p4a 分支（稳定）
p4a.branch = master

# (int) 日志级别 1=error 2=warning 3=info
log_level = 2

# (str) 图标 / 预设（可选，留空用默认）
# icon.filename = %(source.dir)s/mobile/assets/icon.png
# presplash.filename = %(source.dir)s/mobile/assets/presplash.png
