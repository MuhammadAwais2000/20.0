{
    "name": "Sign & Stamp",
    "version": "20.1.1.0.14",
    "category": "Productivity",
    "author": "Muhammad Awais",
    "summary": "Upload a PDF, draw or upload a signature, add stamps, dates and text, then seal the document",
    "depends": ["base", "mail", "web"],
    "external_dependencies": {
        "python": ["pypdf", "reportlab", "pymupdf"],
    },
    "data": [
        "security/ir.access.csv",
        "views/sign_document_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sign_stamp/static/src/**/*",
        ],
    },
    "images": [
        "static/description/banner.png",
        "static/description/icon.png",
        "static/description/screenshot_01_documents.png",
        "static/description/screenshot_02_upload.png",
        "static/description/screenshot_03_editor.png",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
