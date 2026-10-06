/** @odoo-module **/

import {
    Component,
    onMounted,
    onPatched,
    onWillUnmount,
    proxy,
    signal,
    useProps,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { loadPDFJSAssets } from "@web/core/utils/pdfjs";

function uid() {
    return `ov_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function nextFrame() {
    return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}

export class SignStampEditor extends Component {
    static template = "sign_stamp.Editor";
    props = useProps({ ...standardActionServiceProps });

    pdfCanvasRef = signal.ref();
    stageRef = signal.ref();
    sigPadRef = signal.ref();
    scrollAreaRef = signal.ref();

    editor = proxy({
        loading: true,
        saving: false,
        error: "",
        id: false,
        name: _t("Document"),
        docState: "draft",
        readonly: false,
        isSealed: false,
        modeLabel: _t("Edit mode"),
        signerName: "",
        attachmentId: false,
        pdfUrl: "",
        overlays: [],
        selectedId: false,
        tool: "signature",
        sigMode: "draw",
        signatureDataUrl: "",
        stampDataUrl: "",
        dateText: new Date().toISOString().slice(0, 10),
        customText: "",
        textColor: "#1e293b",
        textFontSize: 14,
        page: 1,
        pageCount: 1,
        canvasWidth: 720,
        canvasHeight: 960,
        ready: false,
    });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.pdfDoc = null;
        this.drawing = false;
        this.drag = null;
        this.resize = null;
        this._pendingRender = false;
        this._onWindowMove = this._onWindowMove.bind(this);
        this._onWindowUp = this._onWindowUp.bind(this);

        onMounted(() => this._boot());
        onPatched(() => {
            if (this._pendingRender) {
                this._pendingRender = false;
                this._renderPage();
            }
        });
        onWillUnmount(() => {
            window.removeEventListener("pointermove", this._onWindowMove);
            window.removeEventListener("pointerup", this._onWindowUp);
        });
    }

    get documentId() {
        const action = this.props.action || {};
        return (
            action.params?.document_id ||
            action.context?.document_id ||
            action.context?.active_id ||
            this.props.document_id ||
            false
        );
    }

    get pageOverlays() {
        // Sealed PDFs already contain flattened marks — do not draw draft overlays on top.
        if (this.editor.readonly || this.editor.isSealed) {
            return [];
        }
        return (this.editor.overlays || []).filter((o) => o.page === this.editor.page);
    }

    get canEdit() {
        return !this.editor.readonly && this.editor.docState !== "done";
    }

    get stageStyle() {
        return `width:${this.editor.canvasWidth}px;height:${this.editor.canvasHeight}px;`;
    }

    get fontSizeOptions() {
        return [8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 42, 48, 56, 64, 72];
    }

    overlayStyle(item) {
        return [
            `left:${item.x * 100}%`,
            `top:${item.y * 100}%`,
            `width:${item.width * 100}%`,
            `height:${item.height * 100}%`,
        ].join(";");
    }

    textLabelStyle(item) {
        const color = item.color || this.editor.textColor || "#1e293b";
        const size = item.font_size || this.editor.textFontSize || 14;
        return [`color:${color}`, `font-size:${size}px`].join(";");
    }

    _currentPrefs() {
        return {
            customText: this.editor.customText || "",
            dateText: this.editor.dateText || "",
            textColor: this.editor.textColor || "#1e293b",
            textFontSize: this.editor.textFontSize || 14,
        };
    }

    _applyPrefs(prefs = {}) {
        if (prefs.customText != null) {
            this.editor.customText = prefs.customText;
        }
        if (prefs.dateText) {
            this.editor.dateText = prefs.dateText;
        }
        if (prefs.textColor) {
            this.editor.textColor = prefs.textColor;
        }
        if (prefs.textFontSize) {
            this.editor.textFontSize = Number(prefs.textFontSize) || 14;
        }
    }

    async _persistDraft() {
        if (!this.canEdit || !this.editor.id) {
            return;
        }
        try {
            await this.orm.call("sign.stamp.document", "save_overlay_draft", [
                [this.editor.id],
                this.editor.overlays,
                this._currentPrefs(),
            ]);
        } catch (error) {
            console.warn("Failed to persist overlay draft", error);
        }
    }

    async _boot() {
        window.addEventListener("pointermove", this._onWindowMove);
        window.addEventListener("pointerup", this._onWindowUp);
        try {
            if (!this.documentId) {
                throw new Error(_t("Missing document id. Save the record, then open the editor."));
            }
            const payload = await this.orm.call("sign.stamp.document", "get_editor_payload", [
                this.documentId,
            ]);
            this.editor.id = payload.id;
            this.editor.name = payload.name;
            this.editor.docState = payload.state;
            this.editor.readonly = Boolean(payload.readonly);
            this.editor.isSealed = Boolean(payload.is_sealed);
            this.editor.modeLabel = payload.mode_label || _t("Edit mode");
            this.editor.signerName = payload.signer_name || "";
            this.editor.attachmentId = payload.attachment_id;
            this.editor.pdfUrl = payload.pdf_url;
            this.editor.overlays = payload.overlays || [];
            this.editor.dateText = payload.today || this.editor.dateText;
            this._applyPrefs(payload.prefs || {});
            await this._loadPdf(payload.pdf_url);
            if (this.canEdit) {
                this._initPad();
            }
        } catch (error) {
            console.error("Sign & Stamp editor boot failed:", error);
            this.editor.error = error?.data?.message || error.message || _t("Failed to open editor.");
            this.editor.loading = false;
            this.editor.ready = false;
        }
    }

    async _loadPdf(url) {
        this.editor.loading = true;
        this.editor.error = "";
        this.editor.ready = false;

        await loadPDFJSAssets();
        if (!globalThis.pdfjsLib) {
            throw new Error(_t("PDF.js failed to load."));
        }
        globalThis.pdfjsLib.GlobalWorkerOptions.workerSrc =
            "/web/static/lib/pdfjs/build/pdf.worker.js";

        // Load full bytes first — avoids PDF.js "Stream has ended unexpectedly"
        // when Odoo content streaming is interrupted.
        const pdfUrl = `${url}${url.includes("?") ? "&" : "?"}unique=${Date.now()}`;
        const response = await fetch(pdfUrl, {
            credentials: "include",
            cache: "no-store",
        });
        if (!response.ok) {
            throw new Error(_t("Could not download the PDF (%s).", String(response.status)));
        }
        const data = new Uint8Array(await response.arrayBuffer());
        if (!data.length) {
            throw new Error(_t("The PDF file is empty."));
        }

        this.pdfDoc = await globalThis.pdfjsLib.getDocument({ data }).promise;

        this.editor.pageCount = this.pdfDoc.numPages || 1;
        this.editor.page = 1;
        this.editor.loading = false;
        this.editor.ready = true;
        await nextFrame();
        await this._renderPage();
    }

    async _renderPage() {
        if (!this.pdfDoc) {
            return;
        }
        const canvas = this.pdfCanvasRef();
        if (!canvas) {
            // Canvas not mounted yet — retry after next patch.
            this._pendingRender = true;
            return;
        }

        const page = await this.pdfDoc.getPage(this.editor.page);
        const unscaled = page.getViewport({ scale: 1 });
        const scrollEl = this.scrollAreaRef();
        const available = scrollEl ? Math.max(320, scrollEl.clientWidth - 32) : 900;
        const maxWidth = Math.min(900, available);
        const scale = maxWidth / unscaled.width;
        const viewport = page.getViewport({ scale });

        const context = canvas.getContext("2d");
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        this.editor.canvasWidth = canvas.width;
        this.editor.canvasHeight = canvas.height;

        // Clear previous page pixels.
        context.clearRect(0, 0, canvas.width, canvas.height);
        await page.render({ canvasContext: context, viewport }).promise;
    }

    _initPad() {
        const canvas = this.sigPadRef();
        if (!canvas) {
            return;
        }
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        // Keep the pad transparent so sealed signatures have no white box.
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.strokeStyle = "#0f172a";
        ctx.lineWidth = 2.2;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
    }

    setTool(tool) {
        if (!this.canEdit) {
            return;
        }
        this.editor.tool = tool;
        if (tool === "signature" && this.editor.sigMode === "draw") {
            queueMicrotask(() => this._initPad());
        }
    }

    onStageClick(ev) {
        if (!this.canEdit) {
            return;
        }
        if (ev.target.closest(".o_ss_overlay")) {
            return;
        }
        // Prefer the PDF canvas box so fractions match the rendered page, not
        // any padding around the stage.
        const canvas = this.pdfCanvasRef();
        const box = (canvas || this.stageRef())?.getBoundingClientRect();
        if (!box || !box.width || !box.height) {
            return;
        }
        const x = (ev.clientX - box.left) / box.width;
        const y = (ev.clientY - box.top) / box.height;
        if (x < 0 || y < 0 || x > 1 || y > 1) {
            return;
        }
        this._placeAt(x, y);
    }

    setSigMode(mode) {
        this.editor.sigMode = mode;
        if (mode === "draw") {
            queueMicrotask(() => this._initPad());
        }
    }

    onSignerNameInput(ev) {
        this.editor.signerName = ev.target.value;
    }

    onDateTextInput(ev) {
        this.editor.dateText = ev.target.value;
        this._updateSelectedTextField("text", this.editor.dateText);
        this._persistDraft();
    }

    onCustomTextInput(ev) {
        this.editor.customText = ev.target.value;
        this._updateSelectedTextField("text", this.editor.customText);
        this._persistDraft();
    }

    onTextColorInput(ev) {
        this.editor.textColor = ev.target.value || "#1e293b";
        this._updateSelectedTextField("color", this.editor.textColor);
        this._persistDraft();
    }

    onTextFontSizeInput(ev) {
        this.editor.textFontSize = Number(ev.target.value) || 14;
        this._updateSelectedTextField("font_size", this.editor.textFontSize);
        this._persistDraft();
    }

    _updateSelectedTextField(field, value) {
        const id = this.editor.selectedId;
        if (!id) {
            return;
        }
        this.editor.overlays = this.editor.overlays.map((o) => {
            if (o.id !== id || (o.type !== "text" && o.type !== "date")) {
                return o;
            }
            return { ...o, [field]: value };
        });
    }

    selectOverlay(id) {
        this.editor.selectedId = id;
        const item = (this.editor.overlays || []).find((o) => o.id === id);
        if (!item) {
            return;
        }
        if (item.type === "text" || item.type === "date") {
            if (item.type === "text") {
                this.editor.tool = "text";
                this.editor.customText = item.text || "";
            } else {
                this.editor.tool = "date";
                this.editor.dateText = item.text || this.editor.dateText;
            }
            if (item.color) {
                this.editor.textColor = item.color;
            }
            if (item.font_size) {
                this.editor.textFontSize = Number(item.font_size) || this.editor.textFontSize;
            }
        }
    }

    onPadPointerDown(ev) {
        const canvas = this.sigPadRef();
        if (!canvas) {
            return;
        }
        this.drawing = true;
        canvas.setPointerCapture(ev.pointerId);
        const ctx = canvas.getContext("2d");
        const rect = canvas.getBoundingClientRect();
        ctx.beginPath();
        ctx.moveTo(
            ((ev.clientX - rect.left) / rect.width) * canvas.width,
            ((ev.clientY - rect.top) / rect.height) * canvas.height
        );
    }

    onPadPointerMove(ev) {
        if (!this.drawing) {
            return;
        }
        const canvas = this.sigPadRef();
        if (!canvas) {
            return;
        }
        const ctx = canvas.getContext("2d");
        const rect = canvas.getBoundingClientRect();
        ctx.lineTo(
            ((ev.clientX - rect.left) / rect.width) * canvas.width,
            ((ev.clientY - rect.top) / rect.height) * canvas.height
        );
        ctx.stroke();
    }

    onPadPointerUp() {
        this.drawing = false;
    }

    clearPad() {
        this._initPad();
    }

    useDrawnSignature() {
        const canvas = this.sigPadRef();
        if (!canvas) {
            return;
        }
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        let ink = 0;
        for (let i = 0; i < pixels.length; i += 4) {
            // Count opaque dark-ish ink on a transparent canvas.
            if (pixels[i + 3] > 40 && (pixels[i] < 250 || pixels[i + 1] < 250 || pixels[i + 2] < 250)) {
                ink += 1;
            }
        }
        if (ink < 40) {
            this.notification.add(_t("Draw a signature first."), { type: "warning" });
            return;
        }
        // PNG keeps alpha — no white rectangle on the sealed PDF.
        this.editor.signatureDataUrl = canvas.toDataURL("image/png");
        this._aspectCache = this._aspectCache || {};
        this._aspectCache[this.editor.signatureDataUrl] =
            (canvas.width || 1) / Math.max(canvas.height || 1, 1);
        this.notification.add(_t("Signature ready — click the PDF to place it."), {
            type: "success",
        });
    }

    _readFileAsDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    async _compressDataUrl(dataUrl, maxSide = 800) {
        if (!dataUrl) {
            return dataUrl;
        }
        const image = await new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => resolve(img);
            img.onerror = reject;
            img.src = dataUrl;
        });
        const scale = Math.min(1, maxSide / Math.max(image.width, image.height, 1));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(image.width * scale));
        canvas.height = Math.max(1, Math.round(image.height * scale));
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
        // Punch near-white pixels to alpha so uploaded stamps/signatures seal cleanly.
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const px = imageData.data;
        for (let i = 0; i < px.length; i += 4) {
            if (px[i] >= 245 && px[i + 1] >= 245 && px[i + 2] >= 245) {
                px[i + 3] = 0;
            }
        }
        ctx.putImageData(imageData, 0, 0);
        const out = canvas.toDataURL("image/png");
        this._aspectCache = this._aspectCache || {};
        this._aspectCache[out] = canvas.width / Math.max(canvas.height, 1);
        return out;
    }

    async onSignatureUpload(ev) {
        const file = ev.target.files?.[0];
        if (!file) {
            return;
        }
        const raw = await this._readFileAsDataUrl(file);
        this.editor.signatureDataUrl = await this._compressDataUrl(raw, 700);
        this.notification.add(_t("Signature uploaded — click the PDF to place it."), {
            type: "success",
        });
        ev.target.value = "";
    }

    async onStampUpload(ev) {
        const file = ev.target.files?.[0];
        if (!file) {
            return;
        }
        const raw = await this._readFileAsDataUrl(file);
        this.editor.stampDataUrl = await this._compressDataUrl(raw, 700);
        this.notification.add(_t("Stamp uploaded — click the PDF to place it."), {
            type: "success",
        });
        ev.target.value = "";
    }

    async prevPage() {
        if (this.editor.page <= 1) {
            return;
        }
        this.editor.page -= 1;
        this.editor.selectedId = false;
        await this._renderPage();
    }

    async nextPage() {
        if (this.editor.page >= this.editor.pageCount) {
            return;
        }
        this.editor.page += 1;
        this.editor.selectedId = false;
        await this._renderPage();
    }

    removeOverlay(id) {
        if (!this.canEdit) {
            return;
        }
        this.editor.overlays = this.editor.overlays.filter((o) => o.id !== id);
        if (this.editor.selectedId === id) {
            this.editor.selectedId = false;
        }
        this._persistDraft();
    }

    _imageAspect(dataUrl, fallback = 1) {
        // Prefer natural pixel ratio already known from compress; otherwise fallback.
        const cached = this._aspectCache?.[dataUrl];
        return cached || fallback;
    }

    _placeAt(x, y) {
        if (!this.canEdit) {
            return;
        }
        const tool = this.editor.tool;
        let item = null;

        const pageAspect =
            (this.editor.canvasWidth || 1) / Math.max(this.editor.canvasHeight || 1, 1);

        const clampBox = (cx, cy, w, h) => ({
            x: Math.min(1 - w, Math.max(0, cx - w / 2)),
            y: Math.min(1 - h, Math.max(0, cy - h / 2)),
            width: w,
            height: h,
        });

        // Convert image pixel aspect → fractional page box (page may not be square).
        const boxFromAspect = (cx, cy, baseW, imgAspect) => {
            const w = baseW;
            const h = Math.min(0.45, Math.max(0.04, (w * pageAspect) / Math.max(imgAspect, 0.05)));
            return clampBox(cx, cy, w, h);
        };

        if (tool === "signature") {
            if (!this.editor.signatureDataUrl) {
                this.notification.add(_t("Prepare a drawn or uploaded signature first."), {
                    type: "warning",
                });
                return;
            }
            const aspect = this._imageAspect(this.editor.signatureDataUrl, 280 / 120);
            const box = boxFromAspect(x, y, 0.24, aspect);
            item = {
                id: uid(),
                type: "signature",
                page: this.editor.page,
                ...box,
                aspect,
                data_url: this.editor.signatureDataUrl,
                label: this.editor.signerName,
            };
        } else if (tool === "stamp") {
            if (!this.editor.stampDataUrl) {
                this.notification.add(_t("Upload a stamp image first."), { type: "warning" });
                return;
            }
            const aspect = this._imageAspect(this.editor.stampDataUrl, 1);
            const box = boxFromAspect(x, y, 0.16, aspect);
            item = {
                id: uid(),
                type: "stamp",
                page: this.editor.page,
                ...box,
                aspect,
                data_url: this.editor.stampDataUrl,
            };
        } else if (tool === "date") {
            const box = clampBox(x, y, 0.18, 0.045);
            item = {
                id: uid(),
                type: "date",
                page: this.editor.page,
                ...box,
                text: this.editor.dateText || new Date().toISOString().slice(0, 10),
                color: this.editor.textColor || "#1e293b",
                font_size: this.editor.textFontSize || 14,
            };
        } else if (tool === "text") {
            const text = (this.editor.customText || "").trim();
            if (!text) {
                this.notification.add(_t("Enter some text first."), { type: "warning" });
                return;
            }
            const fontSize = this.editor.textFontSize || 14;
            const lines = Math.min(6, text.split(/\r?\n/).length);
            const approxH = Math.min(0.35, Math.max(0.04, (fontSize * lines * 1.35) / Math.max(this.editor.canvasHeight, 1)));
            const box = clampBox(x, y, 0.32, approxH);
            item = {
                id: uid(),
                type: "text",
                page: this.editor.page,
                ...box,
                text,
                color: this.editor.textColor || "#1e293b",
                font_size: fontSize,
            };
        }

        if (item) {
            this.editor.overlays = [...this.editor.overlays, item];
            this.editor.selectedId = item.id;
            this._persistDraft();
        }
    }

    onOverlayPointerDown(ev, item) {
        if (!this.canEdit) {
            return;
        }
        if (ev.target.closest(".o_ss_handle") || ev.target.closest(".o_ss_remove")) {
            return;
        }
        const stage = this.stageRef();
        if (!stage) {
            return;
        }
        this.editor.selectedId = item.id;
        const stageRect = stage.getBoundingClientRect();
        this.drag = {
            id: item.id,
            offsetX: (ev.clientX - stageRect.left) / stageRect.width - item.x,
            offsetY: (ev.clientY - stageRect.top) / stageRect.height - item.y,
        };
        ev.currentTarget.setPointerCapture?.(ev.pointerId);
    }

    onResizePointerDown(ev, item) {
        const stage = this.stageRef();
        if (!stage) {
            return;
        }
        this.editor.selectedId = item.id;
        const stageRect = stage.getBoundingClientRect();
        const lockAspect = item.type === "signature" || item.type === "stamp";
        const pageAspect =
            (this.editor.canvasWidth || 1) / Math.max(this.editor.canvasHeight || 1, 1);
        const aspect =
            item.aspect ||
            (item.width * pageAspect) / Math.max(item.height || 0.001, 0.001);
        this.resize = {
            id: item.id,
            startW: item.width,
            startH: item.height,
            aspect,
            lockAspect,
            pointerX: (ev.clientX - stageRect.left) / stageRect.width,
            pointerY: (ev.clientY - stageRect.top) / stageRect.height,
        };
    }

    _onWindowMove(ev) {
        const stage = this.stageRef();
        if (!stage) {
            return;
        }
        const rect = stage.getBoundingClientRect();
        const px = (ev.clientX - rect.left) / rect.width;
        const py = (ev.clientY - rect.top) / rect.height;

        if (this.drag) {
            this.editor.overlays = this.editor.overlays.map((o) => {
                if (o.id !== this.drag.id) {
                    return o;
                }
                const x = Math.min(1 - o.width, Math.max(0, px - this.drag.offsetX));
                const y = Math.min(1 - o.height, Math.max(0, py - this.drag.offsetY));
                return { ...o, x, y };
            });
        }

        if (this.resize) {
            const pageAspect =
                (this.editor.canvasWidth || 1) / Math.max(this.editor.canvasHeight || 1, 1);
            this.editor.overlays = this.editor.overlays.map((o) => {
                if (o.id !== this.resize.id) {
                    return o;
                }
                const width = Math.min(
                    0.9,
                    Math.max(0.05, this.resize.startW + (px - this.resize.pointerX))
                );
                let height;
                if (this.resize.lockAspect) {
                    height = Math.min(
                        0.9,
                        Math.max(0.03, (width * pageAspect) / Math.max(this.resize.aspect, 0.05))
                    );
                } else {
                    height = Math.min(
                        0.9,
                        Math.max(0.03, this.resize.startH + (py - this.resize.pointerY))
                    );
                }
                const maxW = Math.min(width, 1 - o.x);
                const maxH = Math.min(height, 1 - o.y);
                const scale = Math.min(maxW / width, maxH / height, 1);
                return {
                    ...o,
                    width: width * scale,
                    height: height * scale,
                    aspect: this.resize.lockAspect ? this.resize.aspect : o.aspect,
                };
            });
        }
    }

    _onWindowUp() {
        const changed = Boolean(this.drag || this.resize);
        this.drag = null;
        this.resize = null;
        if (changed) {
            this._persistDraft();
        }
    }

    async onReset() {
        if (!this.canEdit) {
            return;
        }
        this.editor.overlays = [];
        this.editor.selectedId = false;
        if (this.editor.id) {
            await this.orm.call("sign.stamp.document", "save_overlay_draft", [
                [this.editor.id],
                [],
                this._currentPrefs(),
            ]);
        }
        this.notification.add(_t("Overlays cleared."), { type: "info" });
    }

    async onApplySave() {
        if (!this.canEdit) {
            this.notification.add(_t("This document is already sealed."), { type: "warning" });
            return;
        }
        if (!this.editor.overlays.length) {
            this.notification.add(_t("Place at least one overlay first."), { type: "warning" });
            return;
        }
        this.editor.saving = true;
        try {
            const overlays = [];
            for (const item of this.editor.overlays) {
                const copy = { ...item };
                if (copy.data_url) {
                    copy.data_url = await this._compressDataUrl(copy.data_url, 700);
                }
                overlays.push(copy);
            }
            const result = await this.orm.call("sign.stamp.document", "apply_and_save", [
                [this.editor.id],
                overlays,
                this._currentPrefs(),
            ]);
            this.editor.docState = result.state;
            this.editor.readonly = true;
            this.editor.isSealed = true;
            this.editor.modeLabel = _t("Sealed preview");
            this.editor.overlays = [];
            this.editor.selectedId = false;
            this.editor.attachmentId = result.attachment_id;
            this.notification.add(_t("Document sealed successfully."), { type: "success" });

            // Immediately show the sealed PDF (with stamps baked in).
            if (result.pdf_url) {
                this.editor.pdfUrl = result.pdf_url;
                await this._loadPdf(result.pdf_url);
            }
            if (result.download_url) {
                const link = document.createElement("a");
                link.href = result.download_url;
                link.download = result.filename || "sealed.pdf";
                link.rel = "noopener";
                document.body.appendChild(link);
                link.click();
                link.remove();
            }
        } catch (error) {
            this.notification.add(error?.data?.message || error.message || _t("Save failed."), {
                type: "danger",
            });
        } finally {
            this.editor.saving = false;
        }
    }

    onBack() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sign.stamp.document",
            res_id: this.editor.id || this.documentId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("sign_stamp.editor", SignStampEditor);
