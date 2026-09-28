from odoo import api, models


class SaleChainDashboard(models.TransientModel):
    _name = "sale.chain.dashboard"
    _description = "Sale Chain Dashboard"

    # payment_state → flow column + display label
    _PAYMENT_META = {
        "not_paid": {"column": "invoice_not_paid", "label": "Not Paid"},
        "in_payment": {"column": "invoice_not_paid", "label": "In Payment"},
        "partial": {"column": "invoice_not_paid", "label": "Partially Paid"},
        "blocked": {"column": "invoice_not_paid", "label": "Blocked"},
        "reversed": {"column": "invoice_not_paid", "label": "Reversed"},
        "invoicing_legacy": {"column": "invoice_not_paid", "label": "Legacy"},
        "paid": {"column": "invoice_paid", "label": "Paid"},
    }

    @api.model
    def get_chain_data(self, partner_id):
        """Return flow-map nodes/links for a customer.

        Columns:
          - rfq: draft quotations (Request for Quotation)
          - confirmed: sent quotations (Confirmed Quotation)
          - sale: confirmed sales orders
          - invoice_not_paid: customer invoices not fully paid
          - invoice_paid: customer invoices that are paid
        """
        if not partner_id:
            return self._empty_payload()

        partner = self.env["res.partner"].browse(int(partner_id)).exists()
        if not partner:
            return self._empty_payload()

        commercial = partner.commercial_partner_id
        partner_ids = (commercial | commercial.child_ids).ids

        orders = self.env["sale.order"].search(
            [
                ("partner_id", "child_of", commercial.id),
                ("state", "in", ("draft", "sent", "sale")),
            ],
            order="date_order desc, id desc",
            limit=80,
        )

        nodes = []
        links = []
        counts = {
            "rfq": 0,
            "confirmed": 0,
            "sale": 0,
            "invoice_not_paid": 0,
            "invoice_paid": 0,
        }

        # Origin: client
        origin_id = f"partner-{commercial.id}"
        nodes.append(
            {
                "id": origin_id,
                "type": "partner",
                "column": "origin",
                "name": commercial.display_name,
                "subtitle": "Customer",
                "res_model": "res.partner",
                "res_id": commercial.id,
                "status": False,
            }
        )

        invoice_seen = set()
        state_to_type = {
            "draft": "rfq",
            "sent": "confirmed",
            "sale": "sale",
        }
        state_subtitle = {
            "draft": "Request for Quotation",
            "sent": "Confirmed Quotation",
            "sale": "Sales Order",
        }

        for order in orders:
            ntype = state_to_type[order.state]
            counts[ntype] += 1
            node_id = f"so-{order.id}"
            nodes.append(
                {
                    "id": node_id,
                    "type": ntype,
                    "column": ntype,
                    "name": order.name,
                    "subtitle": state_subtitle[order.state],
                    "res_model": "sale.order",
                    "res_id": order.id,
                    "status": order.state,
                    "amount": order.amount_total,
                    "currency": order.currency_id.symbol or order.currency_id.name,
                }
            )
            links.append(
                {
                    "from": origin_id,
                    "to": node_id,
                    "color": ntype,
                }
            )

            for invoice in order.invoice_ids.filtered(
                lambda m: m.move_type in ("out_invoice", "out_refund") and m.state != "cancel"
            ):
                inv_id = f"inv-{invoice.id}"
                payment_state = invoice.payment_state or "not_paid"
                meta = self._PAYMENT_META.get(
                    payment_state,
                    {"column": "invoice_not_paid", "label": payment_state},
                )
                inv_type = meta["column"]
                if invoice.id not in invoice_seen:
                    invoice_seen.add(invoice.id)
                    counts[inv_type] += 1
                    nodes.append(
                        {
                            "id": inv_id,
                            "type": inv_type,
                            "column": inv_type,
                            "name": invoice.name or invoice.display_name,
                            "subtitle": meta["label"],
                            "res_model": "account.move",
                            "res_id": invoice.id,
                            "status": payment_state,
                            "amount": invoice.amount_total,
                            "currency": invoice.currency_id.symbol or invoice.currency_id.name,
                        }
                    )
                links.append(
                    {
                        "from": node_id,
                        "to": inv_id,
                        "color": inv_type,
                    }
                )

        return {
            "partner": {
                "id": commercial.id,
                "name": commercial.display_name,
            },
            "partner_ids": partner_ids,
            "nodes": nodes,
            "links": links,
            "counts": counts,
            "doc_count": len(nodes),
            "link_count": len(links),
        }

    def _empty_payload(self):
        return {
            "partner": False,
            "partner_ids": [],
            "nodes": [],
            "links": [],
            "counts": {
                "rfq": 0,
                "confirmed": 0,
                "sale": 0,
                "invoice_not_paid": 0,
                "invoice_paid": 0,
            },
            "doc_count": 0,
            "link_count": 0,
        }
