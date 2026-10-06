# -*- coding: utf-8 -*-
import base64
import io

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import BinaryBytes

try:
    from reportlab.pdfgen import canvas as rl_canvas
except ImportError:  # pragma: no cover
    rl_canvas = None


def _tiny_pdf_bytes():
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(300, 400))
    c.drawString(40, 350, "Sign Stamp UAT PDF")
    c.showPage()
    c.save()
    return buf.getvalue()


def _tiny_png_data_url():
    # 1x1 red PNG
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    return "data:image/png;base64," + base64.b64encode(png).decode()


@tagged("post_install", "-at_install", "sign_stamp")
class TestSignStampDocument(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if rl_canvas is None:
            raise AssertionError("reportlab is required for Sign & Stamp tests")
        cls.Document = cls.env["sign.stamp.document"]
        cls.pdf_bytes = _tiny_pdf_bytes()

    def _create_draft(self):
        return self.Document.create(
            {
                "name": "UAT Agreement",
                "pdf": BinaryBytes(self.pdf_bytes),
                "pdf_filename": "uat_agreement.pdf",
                "signer_name": "QA Tester",
            }
        )

    def test_01_draft_editor_payload_uses_source_pdf(self):
        doc = self._create_draft()
        payload = self.Document.get_editor_payload(doc.id)
        self.assertEqual(payload["state"], "draft")
        self.assertFalse(payload["readonly"])
        self.assertFalse(payload["is_sealed"])
        self.assertTrue(payload["attachment_id"])
        self.assertIn(f"/web/content/{payload['attachment_id']}", payload["pdf_url"])
        self.assertEqual(payload["attachment_id"], doc.source_attachment_id.id)

    def test_02_apply_and_save_sets_sealed_state(self):
        doc = self._create_draft()
        overlays = [
            {
                "id": "ov_sig",
                "type": "signature",
                "page": 1,
                "x": 0.1,
                "y": 0.7,
                "width": 0.25,
                "height": 0.08,
                "data_url": _tiny_png_data_url(),
            },
            {
                "id": "ov_date",
                "type": "date",
                "page": 1,
                "x": 0.1,
                "y": 0.85,
                "width": 0.2,
                "height": 0.05,
                "text": "2026-10-05",
            },
        ]
        result = doc.apply_and_save(overlays)
        self.assertEqual(result["state"], "done")
        self.assertTrue(result["readonly"])
        self.assertTrue(result["is_sealed"])
        self.assertTrue(result["attachment_id"])
        self.assertTrue(result["pdf_url"])
        self.assertTrue(result["download_url"])

        doc.invalidate_recordset()
        self.assertEqual(doc.state, "done")
        self.assertTrue(doc.result_attachment_id)
        sealed = doc._to_bytes(doc.result_attachment_id.raw)
        self.assertTrue(sealed.startswith(b"%PDF"))
        self.assertGreater(len(sealed), 100)

    def test_03_sealed_reopen_loads_sealed_pdf_readonly(self):
        """UAT: reopen Open Editor after seal must show sealed PDF, not source."""
        doc = self._create_draft()
        doc.apply_and_save(
            [
                {
                    "id": "ov_stamp",
                    "type": "stamp",
                    "page": 1,
                    "x": 0.55,
                    "y": 0.55,
                    "width": 0.2,
                    "height": 0.2,
                    "data_url": _tiny_png_data_url(),
                }
            ]
        )
        payload = self.Document.get_editor_payload(doc.id)
        self.assertEqual(payload["state"], "done")
        self.assertTrue(payload["readonly"])
        self.assertTrue(payload["is_sealed"])
        self.assertEqual(payload["attachment_id"], doc.result_attachment_id.id)
        self.assertIn(str(doc.result_attachment_id.id), payload["pdf_url"])
        self.assertEqual(payload["overlays"], [])

    def test_04_cannot_reseal_without_reset(self):
        doc = self._create_draft()
        overlays = [
            {
                "id": "ov1",
                "type": "date",
                "page": 1,
                "x": 0.2,
                "y": 0.2,
                "width": 0.2,
                "height": 0.05,
                "text": "2026-10-05",
            }
        ]
        doc.apply_and_save(overlays)
        with self.assertRaises(UserError):
            doc.apply_and_save(overlays)

    def test_05_reset_draft_unlocks_source_editor(self):
        doc = self._create_draft()
        doc.apply_and_save(
            [
                {
                    "id": "ov1",
                    "type": "date",
                    "page": 1,
                    "x": 0.2,
                    "y": 0.2,
                    "width": 0.2,
                    "height": 0.05,
                    "text": "2026-10-05",
                }
            ]
        )
        doc.action_reset_draft()
        self.assertEqual(doc.state, "draft")
        self.assertFalse(doc.result_attachment_id)
        payload = self.Document.get_editor_payload(doc.id)
        self.assertFalse(payload["readonly"])
        self.assertFalse(payload["is_sealed"])
        self.assertEqual(payload["attachment_id"], doc.source_attachment_id.id)

    def test_06_open_editor_action_works_for_sealed(self):
        doc = self._create_draft()
        doc.apply_and_save(
            [
                {
                    "id": "ov1",
                    "type": "date",
                    "page": 1,
                    "x": 0.3,
                    "y": 0.3,
                    "width": 0.2,
                    "height": 0.05,
                    "text": "2026-10-05",
                }
            ]
        )
        action = doc.action_open_editor()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "sign_stamp.editor")
        self.assertEqual(action["params"]["document_id"], doc.id)

    def test_07_overlay_keeps_top_left_placement(self):
        """QA: stamped image must land near the clicked top region, not flipped."""
        try:
            import fitz
        except ImportError:
            self.skipTest("pymupdf required for placement assertion")

        doc = self._create_draft()
        # Place a stamp near the TOP of the page (y=0.05).
        doc.apply_and_save(
            [
                {
                    "id": "ov_top",
                    "type": "stamp",
                    "page": 1,
                    "x": 0.4,
                    "y": 0.05,
                    "width": 0.2,
                    "height": 0.2,
                    "data_url": _tiny_png_data_url(),
                }
            ]
        )
        sealed = doc._to_bytes(doc.result_attachment_id.raw)
        pdf = fitz.open(stream=sealed, filetype="pdf")
        try:
            page = pdf[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
            # Count non-near-white pixels in top vs bottom thirds.
            top_ink = 0
            bottom_ink = 0
            h = pix.height
            w = pix.width
            samples = pix.samples
            n = pix.n  # 3 for RGB
            third = h // 3
            for y in range(h):
                row = y * w * n
                for x in range(w):
                    i = row + x * n
                    r, g, b = samples[i], samples[i + 1], samples[i + 2]
                    if r < 250 or g < 250 or b < 250:
                        if y < third:
                            top_ink += 1
                        elif y >= h - third:
                            bottom_ink += 1
            self.assertGreater(
                top_ink,
                bottom_ink,
                "Stamp placed near top should create more ink in the top third than the bottom third",
            )
        finally:
            pdf.close()

    def test_08_contain_box_preserves_aspect_ratio(self):
        """QA: overlay must fit like CSS object-fit:contain (no stretch)."""
        Document = self.Document
        # Wide image into a squareish box → width-limited.
        x, y, w, h = Document._contain_box(10, 20, 100, 100, 200, 50)
        self.assertAlmostEqual(w, 100.0)
        self.assertAlmostEqual(h, 25.0)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 20.0 + (100 - 25) / 2.0)

        # Tall image into a wide box → height-limited.
        x, y, w, h = Document._contain_box(0, 0, 200, 50, 40, 80)
        self.assertAlmostEqual(h, 50.0)
        self.assertAlmostEqual(w, 25.0)
        self.assertAlmostEqual(x, (200 - 25) / 2.0)
        self.assertAlmostEqual(y, 0.0)

        # Unknown image size → keep the original box (caller must use keep_proportion).
        x, y, w, h = Document._contain_box(1, 2, 30, 40, 0, 0)
        self.assertEqual((x, y, w, h), (1, 2, 30, 40))

    def test_09_custom_text_overlay_seals(self):
        doc = self._create_draft()
        result = doc.apply_and_save(
            [
                {
                    "id": "ov_text",
                    "type": "text",
                    "page": 1,
                    "x": 0.1,
                    "y": 0.2,
                    "width": 0.4,
                    "height": 0.08,
                    "text": "Approved for payment\nRef: UAT-001",
                    "color": "#b91c1c",
                    "font_size": 18,
                }
            ],
            {"textColor": "#b91c1c", "textFontSize": 18, "customText": "Approved for payment"},
        )
        self.assertEqual(result["state"], "done")
        sealed = doc._to_bytes(doc.result_attachment_id.raw)
        self.assertTrue(sealed.startswith(b"%PDF"))
        self.assertGreater(len(sealed), 100)
        overlays, prefs = self.Document._unpack_overlay_state(doc.overlay_json)
        self.assertEqual(overlays[0].get("color"), "#b91c1c")
        self.assertEqual(overlays[0].get("font_size"), 18)
        self.assertEqual(prefs.get("textColor"), "#b91c1c")
        self.assertEqual(prefs.get("textFontSize"), 18)

    def test_10_text_style_prefs_persist_in_draft(self):
        doc = self._create_draft()
        doc.save_overlay_draft(
            [
                {
                    "id": "ov_t",
                    "type": "text",
                    "page": 1,
                    "x": 0.1,
                    "y": 0.1,
                    "width": 0.3,
                    "height": 0.06,
                    "text": "Hello",
                    "color": "#0369a1",
                    "font_size": 20,
                }
            ],
            {"textColor": "#0369a1", "textFontSize": 20, "customText": "Hello"},
        )
        payload = self.Document.get_editor_payload(doc.id)
        self.assertEqual(payload["prefs"]["textColor"], "#0369a1")
        self.assertEqual(payload["prefs"]["textFontSize"], 20)
        self.assertEqual(payload["overlays"][0]["font_size"], 20)
        self.assertEqual(payload["overlays"][0]["color"], "#0369a1")
