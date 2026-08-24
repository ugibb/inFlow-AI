"""内置插件注册表 —— 代码内声明（wechat / obsidian）。

新增插件：新增 `plugins/<id>/` 目录 + 在此注册一行，不触碰既有插件。
"""
from backend.plugins.obsidian.plugin import obsidian_plugin
from backend.plugins.wechat.plugin import wechat_plugin

BUILTIN_PLUGINS = {
    wechat_plugin.id: wechat_plugin,
    obsidian_plugin.id: obsidian_plugin,
}
