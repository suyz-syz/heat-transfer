[app]

# (str) 应用标题（Android 桌面显示名称）
title = 窑衬传热计算

# (str) 包名（APK 的 Java package）
package.name = kilnheat

# (str) 反向域名（与 package.name 组成完整包名 org.example.kilnheat）
package.domain = org.example

# (str) 源目录
source.dir = .

# (list) 打包进 APK 的文件扩展名
source.include_exts = py,png,jpg,kv,atlas,ttf,txt,json,md

# (list) 需要额外包含的目录/文件（计算核心包）
source.include_patterns = kiln_ht/*.py

# (list) 排除的扩展名
source.exclude_exts = spec,pyc

# (str) 应用版本号
version = 1.0.0
# (str) 从文件正则提取版本号（可选）
# version.regex = __version__ = ['\"]([^'\"]+)['\"]
# version.filename = kiln_ht/__init__.py

# (int) Android versionCode（必须随版本递增）
version.code = 1

# (list) Buildozer 使用的依赖（Android 平台通过 python-for-android 打包）
# numpy==2.3.0 为 p4a numpy recipe 当前固定并已验证的版本
requirements = python3,kivy==2.3.0,numpy==2.3.0

# (str) 屏幕方向：portrait / landscape
orientation = portrait

# (bool) 全屏模式
fullscreen = 0

# ============ Android 配置 ============
# (list) Android 权限
android.permissions = INTERNET

# (bool) 自动接受 Android SDK 许可证协议（仅用于自动化/CI，避免 sdkmanager 交互卡死）
android.accept_sdk_license = True

# (int) 目标 API 级别与最低支持
android.api = 34
# numpy==2.3.0 的 p4a recipe 要求 min_ndk_api_support = 24
android.minapi = 24

# (str) 固定 NDK 版本为 r27c：与 GitHub Actions ubuntu 镜像预装的
# 27.3.13750724 (=r27c) 一致，避免 buildozer 自动选用过新的 r28c 导致 p4a 交叉编译失败
android.ndk = 27c

# (list) 目标 CPU 架构
android.archs = arm64-v8a, armeabi-v7a

# (bool) 启用 AndroidX
android.enable_androidx = True

# (bool) 允许应用备份
android.allow_backup = True

# 自定义图标 / 启动图（如使用请放入 assets/ 目录并取消注释）
# presplash.filename = assets/presplash.png
# icon.filename = assets/icon.png

# ============ macOS（可选） ============
osx.package_name = KilnHeat
osx.bundle_name = KilnHeat

# ============ iOS（可选） ============
ios.package_name = org.example.kilnheat

# ============ Windows / Linux（可选） ============
# win.kivy_version = 2.3.0

[buildozer]

# (int) 日志级别
log_level = 2

# (bool) 在 root 下运行时警告
warn_on_root = 1
