import base64
import io
import json
import logging
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SignStampDocument(models.Model):
    _name = "sign.stamp.document"
    _description = "Sign & Stamp Document"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, tracking=True, default="Untitled Document")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Sealed"),
        ],
        default="draft",
        tracking=True,
        required=True,
    )
    pdf = fields.Binary(string="PDF File", required=True, attachment=True)
    pdf_filename = fields.Char(string="PDF Filename")
    source_attachment_id = fields.Many2one(
        "ir.attachment",
        string="Source Attachment",
        compute="_compute_source_attachment_id",
    )
    result_attachment_id = fields.Many2one(
        "ir.attachment",
        string="Sealed Attachment",
        readonly=True,
        copy=False,
    )
    overlay_json = fields.Text(string="Overlay Draft", copy=False)
    signer_name = fields.Char(string="Authorized Signer", default=lambda self: self.env.user.name)
    note = fields.Text(string="Notes")

    @api.depends("pdf")
    def _compute_source_attachment_id(self):
        Attachment = self.env["ir.attachment"]
        for rec in self:
            attachment = Attachment.search(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "=", rec.id),
                    ("res_field", "=", "pdf"),
                ],
                limit=1,
            )
            rec.source_attachment_id = attachment.id if attachment else False

    @api.constrains("pdf", "pdf_filename")
    def _check_pdf(self):
        for rec in self:
            if rec.pdf_filename and not rec.pdf_filename.lower().endswith(".pdf"):
                raise ValidationError(_("Only PDF files are supported."))

    def action_open_editor(self):
        self.ensure_one()
        if not self.pdf and not self.result_attachment_id:
            raise UserError(_("Please upload a PDF before opening the editor."))
        if self.state == "done" and self.result_attachment_id:
            # Sealed documents open the sealed PDF (signatures already baked in).
            pass
        elif not self.source_attachment_id:
            raise UserError(_("PDF attachment is not ready yet. Save the record, then open the editor."))
        return {
            "type": "ir.actions.client",
            "tag": "sign_stamp.editor",
            "name": _("Sign & Stamp Editor"),
            "params": {
                "document_id": self.id,
            },
            "context": {
                "document_id": self.id,
                "active_id": self.id,
            },
            "target": "current",
        }

    def action_reset_draft(self):
        for rec in self:
            # Keep sealed file for audit, but unlock source PDF for new edits.
            rec.write(
                {
                    "state": "draft",
                    "result_attachment_id": False,
                    "overlay_json": self._pack_overlay_state([], {}),
                }
            )
            rec.message_post(body=_("Document reset to Draft. Previous seals were cleared from the editor."))
        return True

    def action_open_result(self):
        self.ensure_one()
        if not self.result_attachment_id:
            raise UserError(_("No sealed PDF yet. Open the editor and click Apply & Save."))
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self.result_attachment_id.id}?download=true",
            "target": "new",
        }

    @api.model
    def get_editor_payload(self, document_id):
        doc = self.browse(document_id).exists()
        if not doc:
            raise UserError(_("Document not found."))

        is_sealed = doc.state == "done" and bool(doc.result_attachment_id)
        prefs = {}
        if is_sealed:
            attachment = doc.result_attachment_id
            # Signatures/stamps/dates are already flattened into this PDF.
            overlays = []
            readonly = True
            # Still restore last text style prefs so a later Reset keeps them.
            _unused, prefs = self._unpack_overlay_state(doc.overlay_json)
        else:
            attachment = doc.source_attachment_id
            if not attachment:
                raise UserError(_("PDF attachment not found. Save the document with a PDF first."))
            overlays, prefs = self._unpack_overlay_state(doc.overlay_json)
            readonly = False

        return {
            "id": doc.id,
            "name": doc.name,
            "state": doc.state,
            "readonly": readonly,
            "is_sealed": is_sealed,
            "signer_name": doc.signer_name or self.env.user.name,
            "attachment_id": attachment.id,
            "result_attachment_id": doc.result_attachment_id.id if doc.result_attachment_id else False,
            "pdf_url": f"/web/content/{attachment.id}?download=false",
            "overlays": overlays,
            "prefs": prefs or {},
            "today": fields.Date.context_today(self).isoformat(),
            "mode_label": _("Sealed preview") if is_sealed else _("Edit mode"),
        }

    def save_overlay_draft(self, overlays, prefs=None):
        self.ensure_one()
        # Keep draft light — drop huge image payloads from draft storage.
        self.overlay_json = self._pack_overlay_state(overlays or [], prefs or {})
        return True

    @api.model
    def _pack_overlay_state(self, overlays, prefs=None):
        return json.dumps(
            {
                "overlays": self._lightweight_overlays(overlays or []),
                "prefs": prefs or {},
            }
        )

    @api.model
    def _unpack_overlay_state(self, raw):
        """Support legacy list JSON and the newer {overlays, prefs} shape."""
        if not raw:
            return [], {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return [], {}
        if isinstance(data, list):
            return data, {}
        if isinstance(data, dict):
            overlays = data.get("overlays") or []
            prefs = data.get("prefs") or {}
            return overlays if isinstance(overlays, list) else [], prefs if isinstance(prefs, dict) else {}
        return [], {}

    @api.model
    def _lightweight_overlays(self, overlays):
        light = []
        for item in overlays or []:
            light.append(
                {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "page": item.get("page"),
                    "x": item.get("x"),
                    "y": item.get("y"),
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "text": item.get("text"),
                    "label": item.get("label"),
                    "color": item.get("color"),
                    "font_size": item.get("font_size"),
                }
            )
        return light

    def apply_and_save(self, overlays, prefs=None):
        """Flatten overlays onto the PDF and store a sealed attachment."""
        self.ensure_one()
        if self.state == "done":
            raise UserError(_("This document is already sealed. Reset to Draft to edit again."))
        if not overlays:
            raise UserError(_("Place at least one signature, stamp, date, or text before saving."))

        try:
            sealed_bytes = self._build_sealed_pdf(overlays)
        except UserError:
            raise
        except Exception as err:
            _logger.exception("Failed to seal PDF for document %s", self.id)
            raise UserError(
                _(
                    "Could not seal this PDF. Try a smaller stamp/signature image or another PDF.\n\n"
                    "Technical details: %s"
                )
                % str(err)
            ) from err

        filename = self.pdf_filename or f"{self.name}.pdf"
        if filename.lower().endswith(".pdf"):
            sealed_name = filename[:-4] + "_sealed.pdf"
        else:
            sealed_name = f"{filename}_sealed.pdf"

        attachment = self.env["ir.attachment"].create(
            {
                "name": sealed_name,
                "type": "binary",
                "raw": sealed_bytes,
                "mimetype": "application/pdf",
                "res_model": self._name,
                "res_id": self.id,
            }
        )
        self.write(
            {
                "result_attachment_id": attachment.id,
                "overlay_json": self._pack_overlay_state(overlays, prefs or {}),
                "state": "done",
            }
        )
        self.message_post(body=_("Document sealed with %s overlay(s).") % len(overlays))
        return {
            "attachment_id": attachment.id,
            "state": "done",
            "readonly": True,
            "is_sealed": True,
            "filename": sealed_name,
            "pdf_url": f"/web/content/{attachment.id}?download=false",
            "download_url": f"/web/content/{attachment.id}?download=true",
        }

    def _to_bytes(self, value):
        """Normalize Odoo 20 BinaryValue / base64 / bytes into raw bytes."""
        if not value:
            return b""
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)
        # Odoo 20 BinaryValue / BinaryBytes
        content = getattr(value, "content", None)
        if content is not None:
            return bytes(content)
        if hasattr(value, "open"):
            with value.open() as stream:
                return stream.read()
        if isinstance(value, str):
            # Legacy base64 string
            try:
                return base64.b64decode(value)
            except Exception:
                return value.encode()
        return bytes(value)

    def _get_source_pdf_bytes(self):
        """Read complete PDF bytes (never truncated bin_size placeholders)."""
        self.ensure_one()
        # Prefer the attachment record — most reliable for Binary(attachment=True).
        attachment = self.source_attachment_id
        if attachment:
            # Odoo 20: ir.attachment.datas was removed; use raw.
            raw = attachment.with_context(bin_size=False).raw
            data = self._to_bytes(raw)
            if data:
                return data
        raw = self.with_context(bin_size=False).pdf
        data = self._to_bytes(raw)
        if not data:
            raise UserError(_("Source PDF is empty."))
        return data

    def _build_sealed_pdf(self, overlays):
        pdf_bytes = self._get_source_pdf_bytes()
        if not pdf_bytes.startswith(b"%PDF"):
            raise UserError(_("The source file does not look like a valid PDF."))

        # Prefer PyMuPDF — far more reliable for stamp/signature insertion.
        try:
            import fitz  # pymupdf

            return self._seal_with_pymupdf(pdf_bytes, overlays, fitz)
        except ImportError:
            _logger.info("PyMuPDF not installed; falling back to pypdf/reportlab")
        except Exception:
            _logger.exception("PyMuPDF sealing failed; trying pypdf fallback")

        try:
            from pypdf import PdfReader, PdfWriter
            from reportlab.pdfgen import canvas as rl_canvas
            from reportlab.lib.utils import ImageReader
        except ImportError as err:
            raise UserError(
                _(
                    "Missing Python packages. Install on the Odoo server:\n"
                    "pip3 install -U pymupdf pypdf reportlab --break-system-packages"
                )
            ) from err

        return self._seal_with_pypdf(pdf_bytes, overlays, PdfReader, PdfWriter, rl_canvas, ImageReader)

    def _prepare_overlay_image(self, raw_b64):
        """Decode/shrink overlay image as RGBA PNG (transparent background)."""
        raw = base64.b64decode(raw_b64)
        try:
            from PIL import Image

            image = Image.open(io.BytesIO(raw))
            image.load()
            image = image.convert("RGBA")
            max_side = 900
            w, h = image.size
            scale = min(1.0, max_side / float(max(w, h) or 1))
            if scale < 1.0:
                resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
                image = image.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    resample,
                )
            image = self._punch_near_white(image)
            out = io.BytesIO()
            image.save(out, format="PNG", optimize=True)
            out.seek(0)
            return out, image.size[0], image.size[1]
        except Exception:
            # Still try to recover natural size so sealing never falls back to stretch.
            img_w = img_h = 0
            try:
                import fitz

                pix = fitz.Pixmap(raw)
                img_w, img_h = int(pix.width), int(pix.height)
                pix = None
            except Exception:
                pass
            return io.BytesIO(raw), img_w, img_h

    @api.model
    def _punch_near_white(self, image, threshold=245):
        """Make near-white pixels fully transparent (no white stamp/signature box)."""
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        pixels = list(image.getdata())
        cleaned = []
        for r, g, b, a in pixels:
            if r >= threshold and g >= threshold and b >= threshold:
                cleaned.append((r, g, b, 0))
            else:
                cleaned.append((r, g, b, a))
        image.putdata(cleaned)
        return image

    @api.model
    def _contain_box(self, box_x, box_y, box_w, box_h, img_w, img_h):
        """Fit image inside box like CSS object-fit: contain (centered, no stretch)."""
        if not img_w or not img_h or box_w <= 0 or box_h <= 0:
            return box_x, box_y, box_w, box_h
        scale = min(box_w / float(img_w), box_h / float(img_h))
        draw_w = max(1.0, img_w * scale)
        draw_h = max(1.0, img_h * scale)
        draw_x = box_x + (box_w - draw_w) / 2.0
        draw_y = box_y + (box_h - draw_h) / 2.0
        return draw_x, draw_y, draw_w, draw_h

    @api.model
    def _parse_color(self, value):
        """Convert #RGB / #RRGGBB to a 0-1 RGB tuple for PDF drawing."""
        raw = (value or "#1e293b").strip()
        if raw.startswith("#"):
            raw = raw[1:]
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        if len(raw) != 6:
            return (0.12, 0.18, 0.28)
        try:
            r = int(raw[0:2], 16) / 255.0
            g = int(raw[2:4], 16) / 255.0
            b = int(raw[4:6], 16) / 255.0
            return (r, g, b)
        except ValueError:
            return (0.12, 0.18, 0.28)

    @api.model
    def _resolve_font_size(self, item, box_h):
        try:
            size = float(item.get("font_size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size > 0:
            return max(6.0, min(96.0, size))
        fallback = max(8.0, min(48.0, float(box_h) * 0.55))
        text = item.get("text") or ""
        if "\n" in text:
            fallback = max(8.0, min(fallback, float(box_h) * 0.28))
        return fallback

    @api.model
    def _insert_overlay_text(self, page, item, box_x, box_y, box_w, box_h, fitz):
        """Draw transparent-background text into a page rect (PyMuPDF)."""
        otype = item.get("type") or "text"
        if otype == "date":
            text = item.get("text") or date.today().isoformat()
        else:
            text = (item.get("text") or "").strip()
        if not text:
            return
        font_size = self._resolve_font_size(item, box_h)
        color = self._parse_color(item.get("color"))
        rect = fitz.Rect(box_x, box_y, box_x + box_w, box_y + box_h)
        page.insert_textbox(
            rect,
            text,
            fontsize=font_size,
            fontname="helv",
            color=color,
            align=0,
        )

    def _seal_with_pymupdf(self, pdf_bytes, overlays, fitz):
        """Stamp overlays using PyMuPDF with object-fit:contain (no stretch)."""
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            for item in overlays:
                page_index = int(item.get("page") or 1) - 1
                if page_index < 0 or page_index >= doc.page_count:
                    continue
                page = doc[page_index]
                page_rect = page.rect
                page_width = float(page_rect.width)
                page_height = float(page_rect.height)

                x_frac = float(item.get("x") or 0)
                y_frac = float(item.get("y") or 0)
                w_frac = float(item.get("width") or 0.2)
                h_frac = float(item.get("height") or 0.08)

                box_w = max(8.0, w_frac * page_width)
                box_h = max(8.0, h_frac * page_height)
                box_x = page_rect.x0 + x_frac * page_width
                box_y = page_rect.y0 + y_frac * page_height

                otype = item.get("type") or "signature"
                if otype in ("signature", "stamp"):
                    data_url = item.get("data_url") or ""
                    raw = data_url.split(",", 1)[1] if "," in data_url else data_url
                    if not raw:
                        continue
                    img_buf, img_w, img_h = self._prepare_overlay_image(raw)
                    # Prefer native keep_proportion=True (CSS object-fit:contain).
                    # Fall back to a pre-fitted rect only when we know pixel size.
                    box_rect = fitz.Rect(box_x, box_y, box_x + box_w, box_y + box_h)
                    if img_w and img_h:
                        draw_x, draw_y, draw_w, draw_h = self._contain_box(
                            box_x, box_y, box_w, box_h, img_w, img_h
                        )
                        fit_rect = fitz.Rect(draw_x, draw_y, draw_x + draw_w, draw_y + draw_h)
                        page.insert_image(
                            fit_rect,
                            stream=img_buf.getvalue(),
                            keep_proportion=True,
                            overlay=True,
                        )
                    else:
                        page.insert_image(
                            box_rect,
                            stream=img_buf.getvalue(),
                            keep_proportion=True,
                            overlay=True,
                        )
                elif otype in ("date", "text"):
                    self._insert_overlay_text(
                        page, item, box_x, box_y, box_w, box_h, fitz
                    )
            return doc.tobytes(deflate=True, garbage=3)
        finally:
            doc.close()

    def _seal_with_pypdf(self, pdf_bytes, overlays, PdfReader, PdfWriter, rl_canvas, ImageReader):
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                raise UserError(_("This PDF is encrypted and cannot be sealed."))

        writer = PdfWriter()
        writer.append(reader)

        by_page = {}
        for item in overlays:
            page = int(item.get("page") or 1)
            by_page.setdefault(page, []).append(item)

        for page_number, page_overlays in by_page.items():
            idx = page_number - 1
            if idx < 0 or idx >= len(writer.pages):
                continue
            target = writer.pages[idx]
            mediabox = target.mediabox
            page_width = float(mediabox.width)
            page_height = float(mediabox.height)

            packet = io.BytesIO()
            c = rl_canvas.Canvas(packet, pagesize=(page_width, page_height))
            for item in page_overlays:
                self._draw_overlay(c, item, page_width, page_height, ImageReader)
            c.save()
            packet.seek(0)
            overlay_pdf = PdfReader(packet, strict=False)
            if overlay_pdf.pages:
                try:
                    target.merge_page(overlay_pdf.pages[0], over=True)
                except TypeError:
                    target.merge_page(overlay_pdf.pages[0])

        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def _draw_overlay(self, canvas, item, page_width, page_height, ImageReader):
        """Draw overlay on a ReportLab canvas (bottom-left origin)."""
        otype = item.get("type") or "signature"
        x_frac = float(item.get("x") or 0)
        y_frac = float(item.get("y") or 0)
        w_frac = float(item.get("width") or 0.2)
        h_frac = float(item.get("height") or 0.08)

        box_w = max(8.0, w_frac * page_width)
        box_h = max(8.0, h_frac * page_height)
        box_x = x_frac * page_width
        box_y = page_height - (y_frac * page_height) - box_h

        if otype in ("signature", "stamp"):
            data_url = item.get("data_url") or ""
            raw = data_url.split(",", 1)[1] if "," in data_url else data_url
            if not raw:
                return
            try:
                img_buf, img_w, img_h = self._prepare_overlay_image(raw)
                image = ImageReader(img_buf)
                if img_w and img_h:
                    draw_x, draw_y, draw_w, draw_h = self._contain_box(
                        box_x, box_y, box_w, box_h, img_w, img_h
                    )
                    canvas.drawImage(
                        image,
                        draw_x,
                        draw_y,
                        width=draw_w,
                        height=draw_h,
                        mask="auto",
                        preserveAspectRatio=True,
                        anchor="c",
                    )
                else:
                    # Unknown size: let ReportLab contain inside the placement box.
                    canvas.drawImage(
                        image,
                        box_x,
                        box_y,
                        width=box_w,
                        height=box_h,
                        mask="auto",
                        preserveAspectRatio=True,
                        anchor="c",
                    )
            except Exception:
                _logger.exception("Failed to draw %s overlay", otype)
            return

        if otype in ("date", "text"):
            if otype == "date":
                text = item.get("text") or date.today().isoformat()
            else:
                text = (item.get("text") or "").strip()
            if not text:
                return
            font_size = self._resolve_font_size(item, box_h)
            r, g, b = self._parse_color(item.get("color"))
            canvas.setFillColorRGB(r, g, b)
            canvas.setFont("Helvetica-Bold" if otype == "date" else "Helvetica", font_size)
            # Transparent background — draw text only.
            text_obj = canvas.beginText(box_x + 2, box_y + box_h - font_size)
            text_obj.setLeading(font_size * 1.2)
            for line in text.splitlines() or [text]:
                text_obj.textLine(line)
            canvas.drawText(text_obj)
