{
    "name": "Voice Notes in Chatter",
    "version": "20.1.1.0.0",
    "category": "Productivity",
    "author": "Muhammad Awais",
    "summary": "Record and share voice notes in any Odoo chatter with preview, captions and duration limits",
    "depends": ["mail", "web"],
    "data": [
        "security/voice_note_security.xml",
        "data/ir_config_parameter_data.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mail_voice_note/static/src/**/*",
        ],
    },
    "images": [
        "static/description/banner.png",
        "static/description/icon.png",
        "static/description/screenshot_chatter_mic.png",
        "static/description/screenshot_recording.png",
        "static/description/screenshot_settings_limit.png",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
