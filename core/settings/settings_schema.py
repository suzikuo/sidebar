"""Authoritative setting definitions shared by native and web surfaces."""

from copy import deepcopy


SETTING_SCHEMA = {
    "general": {
        "title": "通用",
        "description": "应用启动与侧边栏交互行为。",
        "items": {
            "run_on_startup": {
                "label": "开机启动",
                "description": "登录 Windows 后自动启动 Agile Tiles。",
                "control": "toggle",
                "default": False,
            },
            "enable_mouse_hover": {
                "label": "贴边隐藏与悬停显示",
                "description": "鼠标离开时隐藏，移入屏幕边缘时显示。",
                "control": "toggle",
                "default": True,
            },
            "auto_hide_delay": {
                "label": "自动隐藏延迟",
                "description": "鼠标离开后等待多久再隐藏。",
                "control": "number",
                "default": 1000,
                "minimum": 0,
                "maximum": 10000,
                "step": 100,
                "unit": "ms",
            },
            "trigger_zone_width": {
                "label": "边缘触发宽度",
                "description": "鼠标触发侧边栏显示的屏幕边缘宽度。",
                "control": "number",
                "default": 5,
                "minimum": 1,
                "maximum": 50,
                "step": 1,
                "unit": "px",
            },
        },
    },
    "notifications": {
        "title": "通知",
        "description": "控制应用与插件通知。",
        "items": {
            "enabled": {
                "label": "启用通知",
                "description": "允许应用和插件显示通知。",
                "control": "toggle",
                "default": True,
            },
        },
    },
    "appearance": {
        "title": "外观与布局",
        "description": "主题、侧边栏尺寸和详情窗口外观。",
        "items": {
            "theme_mode": {
                "label": "主题模式",
                "description": "选择浅色、深色或跟随系统。",
                "control": "segmented",
                "default": "dark",
                "options": [
                    {"value": "light", "label": "浅色"},
                    {"value": "dark", "label": "深色"},
                    {"value": "system", "label": "系统"},
                ],
            },
            "accent_color": {
                "label": "强调色",
                "description": "用于选中状态和主要操作。",
                "control": "color",
                "default": "#FF6B9D",
            },
            "sidebar_position": {
                "label": "侧边栏位置",
                "description": "选择侧边栏停靠的屏幕边缘。",
                "control": "segmented",
                "default": "right",
                "options": [
                    {"value": "left", "label": "左侧"},
                    {"value": "right", "label": "右侧"},
                    {"value": "top", "label": "顶部"},
                ],
            },
            "sidebar_width": {
                "label": "展开宽度",
                "description": "侧边栏展开后的宽度。",
                "control": "range",
                "default": 500,
                "minimum": 320,
                "maximum": 1200,
                "step": 10,
                "unit": "px",
            },
            "collapsed_width": {
                "label": "收起宽度",
                "description": "侧边栏收起后的图标栏宽度。",
                "control": "range",
                "default": 48,
                "minimum": 32,
                "maximum": 96,
                "step": 1,
                "unit": "px",
            },
            "icon_size": {
                "label": "图标尺寸",
                "description": "侧边栏插件图标尺寸。",
                "control": "range",
                "default": 40,
                "minimum": 20,
                "maximum": 96,
                "step": 1,
                "unit": "px",
            },
            "peek_width": {
                "label": "隐藏边框宽度",
                "description": "侧边栏隐藏时保留在屏幕边缘的宽度。",
                "control": "range",
                "default": 2,
                "minimum": 0,
                "maximum": 10,
                "step": 1,
                "unit": "px",
            },
            "sidebar_bg_opacity": {
                "label": "侧边栏不透明度",
                "description": "侧边栏背景不透明度。",
                "control": "range",
                "default": 0.9,
                "minimum": 0.1,
                "maximum": 1.0,
                "step": 0.05,
                "format": "percent",
            },
            "detail_bg_opacity": {
                "label": "详情页不透明度",
                "description": "插件详情页背景不透明度。",
                "control": "range",
                "default": 0.9,
                "minimum": 0.1,
                "maximum": 1.0,
                "step": 0.05,
                "format": "percent",
            },
            "sidebar_height_percent": {
                "label": "侧边栏高度",
                "description": "侧边栏占可用屏幕高度的比例。",
                "control": "range",
                "default": 0.8,
                "minimum": 0.2,
                "maximum": 1.0,
                "step": 0.05,
                "format": "percent",
            },
            "sidebar_hidden_height_percent": {
                "label": "隐藏状态高度",
                "description": "隐藏状态下侧边栏占屏幕高度的比例。",
                "control": "range",
                "default": 0.8,
                "minimum": 0.2,
                "maximum": 1.0,
                "step": 0.05,
                "format": "percent",
            },
            "sidebar_y_offset": {
                "label": "垂直偏移",
                "description": "侧边栏相对屏幕中心的垂直偏移。",
                "control": "number",
                "default": 0,
                "minimum": -2000,
                "maximum": 2000,
                "step": 1,
                "unit": "px",
            },
            "sidebar_border_color": {
                "label": "隐藏边框颜色",
                "description": "侧边栏隐藏时屏幕边缘提示条的颜色。",
                "control": "color",
                "default": "#FF0000",
            },
            "detail_min_height": {
                "label": "详情页最小高度",
                "description": "插件详情窗口的最小高度。",
                "control": "range",
                "default": 700,
                "minimum": 300,
                "maximum": 1200,
                "step": 10,
                "unit": "px",
            },
            "font_family": {
                "label": "字体",
                "description": "应用界面使用的字体。",
                "control": "text",
                "default": "Segoe UI",
                "maximumLength": 128,
            },
            "font_size": {
                "label": "字号",
                "description": "应用界面的基础字号。",
                "control": "range",
                "default": 13,
                "minimum": 8,
                "maximum": 32,
                "step": 1,
                "unit": "pt",
            },
            "font_weight": {
                "label": "字重",
                "description": "应用界面的基础字重。",
                "control": "select",
                "default": "normal",
                "options": [
                    {"value": "light", "label": "细"},
                    {"value": "normal", "label": "常规"},
                    {"value": "medium", "label": "中等"},
                    {"value": "bold", "label": "粗体"},
                ],
            },
        },
    },
    "shortcuts": {
        "title": "快捷键",
        "description": "全局操作快捷键。",
        "items": {
            "toggle_sidebar": {
                "label": "显示/隐藏侧边栏",
                "description": "切换侧边栏展开与收起。",
                "control": "shortcut",
                "default": "alt+space",
                "maximumLength": 128,
            },
        },
    },
}


def get_setting_defaults():
    defaults = {
        category: {
            key: deepcopy(definition["default"])
            for key, definition in group["items"].items()
        }
        for category, group in SETTING_SCHEMA.items()
    }
    defaults["plugins"] = {"enabled": [], "disabled": []}
    return defaults


def get_public_setting_schema():
    return deepcopy(SETTING_SCHEMA)


def get_setting_definition(category, key):
    group = SETTING_SCHEMA.get(category)
    if group is None:
        return None
    return group["items"].get(key)
