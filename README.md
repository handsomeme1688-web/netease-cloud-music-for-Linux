# 网易云音乐 · Ubuntu 独立窗口版

将 <https://music.163.com/st/webplayer> 作为独立 Ubuntu 桌面应用运行。
使用 Python 3、GTK 3 和 WebKitGTK 4.1，不需要安装或借用 Chrome、Chromium、Electron。
它拥有独立窗口、应用菜单入口和独立的网页登录数据；仍需联网访问网易云音乐网页。
这是非官方网页封装客户端，界面、账号登录、曲库、会员权限及播放能力由原网站提供。

## 安装 .deb 包

从 [Releases 页面](https://github.com/handsomeme1688-web/netease-cloud-music-webkit/releases) 下载最新的 `.deb` 安装包。

在 Ubuntu 桌面打开终端，切换到安装包所在目录后运行：

```sh
sudo apt install ./netease-cloud-music-webkit_1.0.1_all.deb
```

APT 会安装所需系统依赖。安装完成后，在应用菜单中搜索“网易云音乐”，或在终端执行：

```sh
netease-cloud-music
```

此包适用于软件源提供 `gir1.2-webkit2-4.1` 的 Ubuntu 版本。
`all` 表示本应用使用 Python 源码，不包含绑定 CPU 架构的二进制；WebKitGTK 等系统依赖仍须支持你的系统架构。
运行需要图形桌面会话和互联网连接。

## 仅安装到当前用户

先安装依赖：

```sh
sudo apt install python3 python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gstreamer1.0-plugins-good gstreamer1.0-libav
```

解压源码包，在源码目录运行，无需 sudo：

```sh
bash install.sh
```

默认程序目录是 `~/.local/share/netease-cloud-music/app`，启动器为 `~/.local/bin/netease-cloud-music`。
应用菜单入口保存在 `~/.local/share/applications`，不依赖 `~/.local/bin` 是否已加入 `PATH`。
安装和卸载支持绝对路径的 `XDG_DATA_HOME`、`XDG_CACHE_HOME`、`XDG_CONFIG_HOME`，并允许用 `XDG_BIN_HOME` 改变启动器目录。
含空格的路径会正确引用。卸载时请保持与安装时相同的这些环境变量。

## 登录与播放

首次运行后直接在官方网页内登录；登录数据与浏览器分开保存，重启后继续使用。
登录 Cookie 默认保存为 `~/.local/share/netease-cloud-music/cookies.sqlite`，其他网页数据位于同目录的 `webkit/`。
缓存目录为 `~/.cache/netease-cloud-music/webkit/`，窗口配置为 `~/.config/netease-cloud-music/window.json`。相应 XDG 环境变量可改变基础目录。
本程序不收集或转发账号密码，也不绕过原网站的会员、版权、区域或播放限制。
如网站不支持当前 WebKitGTK 版本、出现网络限制或要求额外验证，可能影响某些功能。
网页目前只接受特定浏览器标识，因此应用发送 Firefox 兼容标识以通过该检查；实际运行引擎始终是 WebKitGTK，也无需安装 Firefox。
关闭窗口会停止播放。支持 Ctrl+R 刷新、Alt+方向键前进/后退、Ctrl++ / Ctrl+- 缩放和 Ctrl+Q 退出。
已移除顶部工具栏与标题栏，网页直接从窗口顶边显示。最小化、最大化／还原、关闭三个原生按钮集成在内容区右上角，网易云顶栏右侧留出空间，避免遮挡账号和皮肤等入口。F10 不再恢复工具栏。Alt+Home 返回播放器首页，Alt+F4 关闭窗口，Ubuntu 默认可按住 Super（Windows 徽标键）拖动窗口。弹窗同样使用内部窗口按钮；视频全屏时暂时隐藏按钮，退出全屏后恢复。

## 窗口显示

右上角窗口按钮采用透明底和灰蓝细线图标，与网页顶栏保持接近的视觉风格；只有悬停时显示轻微反馈，关闭按钮悬停时变为网易云红色。

Wayland 桌面下，应用优先使用原生 Wayland，连接不可用时自动回退到 X11。此设置仅作用于本应用，不会修改系统的显示器、缩放或动画设置。窗口切换焦点、最小化和恢复时不会重建最大化按钮。

如需排查旧驱动兼容性，先退出应用，再用 `NETEASE_MUSIC_BACKEND=x11 netease-cloud-music` 临时选择 X11；也可用 `NETEASE_MUSIC_BACKEND=wayland` 强制原生 Wayland。已经运行的实例须退出后才会使用新的显示后端。

## Ubuntu 22.04 与启动排查

最低运行依赖为 Python 3.10、WebKitGTK 2.36。v1.0.1 为 WebKitGTK 2.36–2.38 补充了旧版 JavaScript 接口和网页响应处理兼容，避免在创建窗口时调用不存在的方法。

v1.0.1 同时修正了首页被当成下载文件的处理：对返回 HTML 的播放器首页明确执行页面显示；对非网页内容、空响应或 HTTP 错误显示具体状态、WebKit 内容类型和原始响应头，不再弹出保存 `webplayer` 的对话框。正常重定向和其他地址的下载仍由各自流程处理。

如果窗口出现但网页全白，先完全退出应用，再在终端检查运行版本：

```sh
netease-cloud-music --check
```

若怀疑是显卡渲染兼容问题，可临时尝试：

```sh
WEBKIT_DISABLE_DMABUF_RENDERER=1 netease-cloud-music
```

这是 WebKitGTK 提供的渲染排查选项，仅影响此次启动；不同版本和显卡的效果可能不同。应用采用单实例运行，已有窗口必须先关闭，重新运行命令才能让新的环境设置生效。若仍然白屏，请提供 `--check` 输出及完全退出后重新启动时的终端错误。

## 卸载

若使用 .deb 安装：

```sh
sudo apt remove netease-cloud-music-webkit
```

若使用当前用户安装脚本安装，在原源码目录运行：

```sh
bash uninstall.sh
```

也可运行安装目录中的 `uninstall.sh`。默认卸载保留登录数据、缓存与窗口配置。
要同时删除当前用户安装的登录数据、缓存与窗口配置，请先退出应用，然后运行：

```sh
bash uninstall.sh --purge
```

## 从源码构建

构建只需要 `bash`、`dpkg-deb`、`tar` 和常用系统工具，不需要 root、网络或安装 GUI 运行依赖：

```sh
bash build-package.sh /绝对路径/outputs
```

生成 `netease-cloud-music-webkit_1.0.1_all.deb` 和 `netease-cloud-music-1.0.1-source.tar.gz`。
未提供输出目录时，使用源码目录下的 `dist`。
在已安装运行依赖的环境中，可运行兼容性回归测试（无需打开窗口）：

```sh
python3 -m unittest discover -s tests -v
```

图标的原始品牌图像来自[网易云音乐官网提供的高清标识](https://p3.music.126.net/9z9CeujRSPOPm7Rq2DFw_g==/6674035581283071.jpg)，在 SVG 中采用参考 macOS 的连续圆角裁剪、透明留白与轻微阴影，以适配桌面图标的显示。本软件仍是非官方网页封装。
