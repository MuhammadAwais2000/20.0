{
    "name": "URL Attachment Downloader",
    "version": "20.0.1.0.1",
    "category": "Productivity",
    "author": "Muhammad Awais",
    "summary": "Download media from a URL with yt-dlp and save it as an Odoo attachment",
    "depends": ["base", "mail", "web"],
    "external_dependencies": {
        "python": ["yt_dlp"],
    },
    "data": [
        "security/ir.access.csv",
        "views/download_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "yt_dlp_downloader/static/src/**/*",
        ],
    },
    "images": [
        "static/description/banner.png",
        "static/description/features.png",
        "static/description/howto.png",
        "static/description/screenshot.png",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
