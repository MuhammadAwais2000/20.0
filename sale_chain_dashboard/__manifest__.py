{
    "name": "Sale Chain Dashboard",
    "version": "20.0.1.0.1",
    "category": "Sales",
    "author": "Muhammad Awais",
    "summary": "Flow map of RFQ, quotation, sales order and invoices by payment status",
    "depends": ["sale_management", "account"],
    "data": [
        "security/ir.access.csv",
        "views/chain_dashboard_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sale_chain_dashboard/static/src/**/*",
        ],
    },
    "images": [
        "static/description/banner.png",
        "static/description/screenshot.png",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
