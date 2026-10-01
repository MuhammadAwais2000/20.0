import logging
import os
import shutil
import tempfile

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import yt_dlp
except ImportError:  # pragma: no cover
    yt_dlp = None


def _find_ffmpeg_dir():
    """Return directory containing ffmpeg, or False."""
    for candidate in (
        shutil.which("ffmpeg"),
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/bin/ffmpeg",
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return os.path.dirname(os.path.abspath(candidate))
    return False


class YtDlpDownload(models.Model):
    _name = "yt.dlp.download"
    _description = "URL Attachment Download"
    _order = "id desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string="Title", tracking=True)
    url = fields.Char(string="Media URL", required=True, tracking=True)
    format_mode = fields.Selection(
        [
            ("best", "Best video + audio"),
            ("bestvideo", "Best video only"),
            ("bestaudio", "Best audio only"),
        ],
        string="Format",
        default="best",
        required=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Downloaded"),
            ("error", "Error"),
        ],
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )
    attachment_id = fields.Many2one("ir.attachment", string="Attachment", copy=False, readonly=True)
    file_name = fields.Char(related="attachment_id.name", string="File Name")
    mimetype = fields.Char(related="attachment_id.mimetype", string="MIME Type")
    file_size = fields.Integer(related="attachment_id.file_size", string="Size")
    extractor = fields.Char(string="Extractor", readonly=True, copy=False)
    duration = fields.Float(string="Duration (sec)", readonly=True, copy=False)
    error_message = fields.Text(string="Error", readonly=True, copy=False)
    note = fields.Text(string="Notes")

    def action_reset_draft(self):
        self.write(
            {
                "state": "draft",
                "error_message": False,
            }
        )
        return True

    def action_open_attachment(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("No attachment available. Download the media first."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "ir.attachment",
            "view_mode": "form",
            "res_id": self.attachment_id.id,
            "target": "current",
        }

    def action_download(self):
        if yt_dlp is None:
            raise UserError(
                _(
                    "Python package 'yt-dlp' is not installed on the server.\n"
                    "Install it with: pip install -U yt-dlp"
                )
            )
        for record in self:
            record._download_to_attachment()
        return True

    def _build_ydl_opts(self, outtmpl):
        self.ensure_one()
        ffmpeg_dir = _find_ffmpeg_dir()
        # Prefer merged A/V when ffmpeg exists; otherwise use a single progressive stream.
        if ffmpeg_dir:
            format_map = {
                "best": "bv*+ba/b",
                "bestvideo": "bv*/b",
                "bestaudio": "ba/b",
            }
        else:
            _logger.warning("ffmpeg not found; falling back to single-stream formats")
            format_map = {
                "best": "b",
                "bestvideo": "bv/b",
                "bestaudio": "ba/b",
            }

        opts = {
            "outtmpl": outtmpl,
            "format": format_map.get(self.format_mode, "b"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "overwrites": True,
            # Prefer IPv4 (more reliable in Docker networks)
            "source_address": "0.0.0.0",
            "merge_output_format": "mp4",
        }
        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir
        return opts


    def _download_to_attachment(self):
        self.ensure_one()
        if not self.url or not self.url.strip():
            raise UserError(_("Please provide a valid media URL."))

        url = self.url.strip()
        with tempfile.TemporaryDirectory(prefix="odoo_yt_dlp_") as tmpdir:
            outtmpl = os.path.join(tmpdir, "%(id)s.%(ext)s")
            ydl_opts = self._build_ydl_opts(outtmpl)
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info is None:
                        raise UserError(_("yt-dlp returned no information for this URL."))
                    # playlists are blocked, but keep a safe fallback
                    if info.get("_type") == "playlist":
                        entries = info.get("entries") or []
                        if not entries:
                            raise UserError(_("Playlist download is disabled."))
                        info = entries[0]
                    prepared = ydl.prepare_filename(info)
                    filepath = self._resolve_downloaded_path(prepared, tmpdir)
            except UserError:
                raise
            except Exception as exc:
                _logger.exception("yt-dlp download failed for %s", url)
                self.write(
                    {
                        "state": "error",
                        "error_message": str(exc),
                    }
                )
                raise UserError(_("Download failed:\n%s") % exc) from exc

            if not filepath or not os.path.isfile(filepath):
                self.write(
                    {
                        "state": "error",
                        "error_message": _("Downloaded file was not found on disk."),
                    }
                )
                raise UserError(_("Downloaded file was not found on disk."))

            with open(filepath, "rb") as handle:
                raw = handle.read()

            if not raw:
                self.write(
                    {
                        "state": "error",
                        "error_message": _("Downloaded file is empty."),
                    }
                )
                raise UserError(_("Downloaded file is empty."))

            filename = os.path.basename(filepath)
            title = info.get("title") or filename
            mimetype = self._guess_mimetype(filename)
            attachment = self.env["ir.attachment"].create(
                {
                    "name": filename,
                    # Odoo 20+: use `raw` (binary bytes). `datas` is ignored.
                    "raw": raw,
                    "res_model": self._name,
                    "res_id": self.id,
                    "type": "binary",
                    "mimetype": mimetype,
                    "description": _("Downloaded from %s") % url,
                }
            )
            if not attachment.file_size:
                raise UserError(
                    _("Attachment was created but file content was not stored. Check filestore permissions.")
                )
            # drop previous attachment if re-download
            if self.attachment_id and self.attachment_id != attachment:
                self.attachment_id.unlink()

            self.write(
                {
                    "name": title,
                    "attachment_id": attachment.id,
                    "extractor": info.get("extractor") or info.get("extractor_key") or False,
                    "duration": info.get("duration") or 0.0,
                    "state": "done",
                    "error_message": False,
                }
            )
            self.message_post(body=_("Media downloaded and stored as attachment: %s") % filename)
        return True

    @api.model
    def _resolve_downloaded_path(self, prepared_path, tmpdir):
        """Return the actual file path after yt-dlp download/merge."""
        if prepared_path and os.path.isfile(prepared_path):
            return prepared_path
        # After merge, extension may differ (e.g. .mp4)
        base, _ext = os.path.splitext(prepared_path or "")
        if base:
            for candidate_ext in (".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".opus"):
                candidate = base + candidate_ext
                if os.path.isfile(candidate):
                    return candidate
        # Last resort: first file in temp dir
        files = [
            os.path.join(tmpdir, name)
            for name in os.listdir(tmpdir)
            if os.path.isfile(os.path.join(tmpdir, name))
        ]
        if len(files) == 1:
            return files[0]
        if files:
            files.sort(key=lambda path: os.path.getsize(path), reverse=True)
            return files[0]
        return False

    @api.model
    def _guess_mimetype(self, filename):
        ext = os.path.splitext(filename)[1].lower()
        mapping = {
            ".mp4": "video/mp4",
            ".mkv": "video/x-matroska",
            ".webm": "video/webm",
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".opus": "audio/opus",
            ".ogg": "audio/ogg",
            ".wav": "audio/wav",
        }
        return mapping.get(ext, "application/octet-stream")
