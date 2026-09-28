/** @odoo-module **/

import { Component, onMounted, onPatched, proxy, signal, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { RecordSelector } from "@web/core/record_selectors/record_selector";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { render } from "@web/owl2/utils";

const TYPE_META = {
    partner: { label: "Client", color: "#5b6b7c", className: "o_scd_type_partner" },
    rfq: { label: "RFQ", color: "#3b82f6", className: "o_scd_type_rfq" },
    confirmed: { label: "Confirmed Quotation", color: "#0ea5e9", className: "o_scd_type_confirmed" },
    sale: { label: "Sales", color: "#2563eb", className: "o_scd_type_sale" },
    invoice_not_paid: {
        label: "Invoice Not Paid",
        color: "#f59e0b",
        className: "o_scd_type_invoice_not_paid",
    },
    invoice_paid: {
        label: "Invoice Paid",
        color: "#10b981",
        className: "o_scd_type_invoice_paid",
    },
};

export class SaleChainFlowMap extends Component {
    static template = "sale_chain_dashboard.FlowMap";
    static components = { RecordSelector };
    props = useProps({ ...standardActionServiceProps });

    canvasRef = signal.ref();
    svgRef = signal.ref();

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = proxy({
            partnerId: false,
            loading: false,
            data: {
                partner: false,
                nodes: [],
                links: [],
                counts: {
                    rfq: 0,
                    confirmed: 0,
                    sale: 0,
                    invoice_not_paid: 0,
                    invoice_paid: 0,
                },
                doc_count: 0,
                link_count: 0,
            },
        });

        this.columns = [
            { key: "origin", label: _t("ORIGIN") },
            { key: "rfq", label: _t("RFQ") },
            { key: "confirmed", label: _t("CONFIRMED QUOTATION") },
            { key: "sale", label: _t("SALES ORDER") },
            { key: "invoice_not_paid", label: _t("INVOICE NOT PAID") },
            { key: "invoice_paid", label: _t("INVOICE PAID") },
        ];
        this.typeMeta = TYPE_META;

        onMounted(() => this._drawLinks());
        onPatched(() => this._drawLinks());
    }

    get legendItems() {
        const counts = this.state.data.counts || {};
        const labels = {
            rfq: _t("RFQ"),
            confirmed: _t("Confirmed Quotation"),
            sale: _t("Sales"),
            invoice_not_paid: _t("Not Paid"),
            invoice_paid: _t("Paid"),
        };
        return ["rfq", "confirmed", "sale", "invoice_not_paid", "invoice_paid"].map((key) => ({
            key,
            label: labels[key],
            color: TYPE_META[key].color,
            count: counts[key] || 0,
        }));
    }

    get nodesByColumn() {
        const map = {
            origin: [],
            rfq: [],
            confirmed: [],
            sale: [],
            invoice_not_paid: [],
            invoice_paid: [],
        };
        for (const node of this.state.data.nodes || []) {
            if (map[node.column]) {
                map[node.column].push(node);
            }
        }
        return map;
    }

    get summaryText() {
        const docs = this.state.data.doc_count || 0;
        const links = this.state.data.link_count || 0;
        return _t("%s docs / %s links", docs, links);
    }

    async onPartnerUpdate(resId) {
        this.state.partnerId = resId || false;
        await this.loadChain();
        render(this);
    }

    async loadChain() {
        if (!this.state.partnerId) {
            this.state.data = {
                partner: false,
                nodes: [],
                links: [],
                counts: {
                    rfq: 0,
                    confirmed: 0,
                    sale: 0,
                    invoice_not_paid: 0,
                    invoice_paid: 0,
                },
                doc_count: 0,
                link_count: 0,
            };
            return;
        }
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("sale.chain.dashboard", "get_chain_data", [
                this.state.partnerId,
            ]);
        } finally {
            this.state.loading = false;
        }
    }

    openRecord(node) {
        if (!node?.res_model || !node?.res_id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: node.res_model,
            res_id: node.res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    nodeClass(node) {
        return TYPE_META[node.type]?.className || "";
    }

    formatAmount(node) {
        if (node.amount === undefined || node.amount === false || node.amount === null) {
            return "";
        }
        const cur = node.currency || "";
        return `${cur} ${Number(node.amount).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })}`;
    }

    _drawLinks() {
        const svg = this.svgRef();
        const canvas = this.canvasRef();
        if (!svg || !canvas) {
            return;
        }
        const canvasRect = canvas.getBoundingClientRect();
        svg.setAttribute("width", String(canvas.scrollWidth || canvasRect.width));
        svg.setAttribute("height", String(canvas.scrollHeight || canvasRect.height));
        svg.innerHTML = "";

        const links = this.state.data.links || [];
        for (const link of links) {
            const fromEl = canvas.querySelector(`[data-node-id="${link.from}"]`);
            const toEl = canvas.querySelector(`[data-node-id="${link.to}"]`);
            if (!fromEl || !toEl) {
                continue;
            }
            const a = fromEl.getBoundingClientRect();
            const b = toEl.getBoundingClientRect();
            const x1 = a.right - canvasRect.left + canvas.scrollLeft;
            const y1 = a.top + a.height / 2 - canvasRect.top + canvas.scrollTop;
            const x2 = b.left - canvasRect.left + canvas.scrollLeft;
            const y2 = b.top + b.height / 2 - canvasRect.top + canvas.scrollTop;
            const dx = Math.max(40, (x2 - x1) * 0.45);
            const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
            path.setAttribute("d", `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`);
            path.setAttribute("fill", "none");
            path.setAttribute("stroke", TYPE_META[link.color]?.color || "#94a3b8");
            path.setAttribute("stroke-width", "1.6");
            path.setAttribute("stroke-dasharray", "5 4");
            path.setAttribute("opacity", "0.85");
            svg.appendChild(path);
        }
    }
}

registry.category("actions").add("sale_chain_dashboard.flow_map", SaleChainFlowMap);
