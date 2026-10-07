from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mail_voice_note_max_duration = fields.Integer(
        string="Max Voice Note Duration (seconds)",
        config_parameter="mail_voice_note.max_duration",
        default=60,
        help="Maximum length allowed for voice notes recorded in chatter (5–60 seconds).",
    )
    mail_voice_note_allow_caption = fields.Boolean(
        string="Allow Audio Captions",
        config_parameter="mail_voice_note.allow_caption",
        default=True,
        help="When enabled, users can add an optional text caption before sending a voice note. "
        "When disabled, the voice note is sent automatically after recording.",
    )

    @api.onchange("mail_voice_note_max_duration")
    def _onchange_mail_voice_note_max_duration(self):
        if self.mail_voice_note_max_duration:
            self.mail_voice_note_max_duration = max(5, min(60, self.mail_voice_note_max_duration))

    def set_values(self):
        for settings in self:
            if settings.mail_voice_note_max_duration:
                settings.mail_voice_note_max_duration = max(
                    5, min(60, settings.mail_voice_note_max_duration)
                )
        return super().set_values()
