from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        result = super().session_info()
        ICP = self.env["ir.config_parameter"].sudo()
        max_duration = ICP.get_int("mail_voice_note.max_duration", 60)
        max_duration = max(5, min(60, max_duration))
        allow_caption = ICP.get_bool("mail_voice_note.allow_caption", True)
        result["mail_voice_note_max_duration"] = max_duration
        result["mail_voice_note_allow_caption"] = allow_caption
        result["mail_voice_note_can_record"] = self.env.user.has_group(
            "mail_voice_note.group_mail_voice_note"
        )
        return result
