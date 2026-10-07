import { onMounted, useEffect } from "@odoo/owl";

import { Composer } from "@mail/core/common/composer";
import { _t } from "@web/core/l10n/translation";
import { session } from "@web/session";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

function parseElapsedSeconds(elapsed) {
    if (!elapsed || typeof elapsed !== "string") {
        return 0;
    }
    const parts = elapsed.split(":").map((part) => parseInt(part.trim(), 10));
    if (parts.length !== 2 || parts.some((n) => Number.isNaN(n))) {
        return 0;
    }
    return parts[0] * 60 + parts[1];
}

patch(Composer.prototype, {
    setup() {
        super.setup(...arguments);
        this.voiceNoteNotification = useService("notification");
        this._voiceNoteAutoSendPending = false;
        this._voiceNoteLimitNotified = false;

        const maxDuration = session.mail_voice_note_max_duration || 60;

        const tryStartPendingVoiceNote = () => {
            if (!this.env.inChatter?.startVoiceNote) {
                return;
            }
            if (!this.voiceRecorder || this.voiceRecorder.recording) {
                return;
            }
            if (!session.mail_voice_note_can_record) {
                this.env.inChatter.startVoiceNote = false;
                return;
            }
            this.env.inChatter.startVoiceNote = false;
            this.voiceRecorder.onClick();
        };

        // Start recording when the chatter top-bar mic was clicked.
        onMounted(tryStartPendingVoiceNote);
        useEffect(tryStartPendingVoiceNote, () => [
            this.env.inChatter?.startVoiceNote,
            this.voiceRecorder,
            this.voiceRecorder?.recording,
        ]);

        // Enforce a shorter limit than the built-in 60s recorder cap when configured.
        useEffect(
            () => {
                if (maxDuration >= 60 || !this.voiceRecorder?.recording) {
                    this._voiceNoteLimitNotified = false;
                    return;
                }
                const elapsed = parseElapsedSeconds(this.voiceRecorder.elapsed);
                if (elapsed >= Math.max(0, maxDuration - 5) && elapsed < maxDuration) {
                    this.voiceRecorder.limitWarning = true;
                }
                if (elapsed >= maxDuration && !this._voiceNoteLimitNotified) {
                    this._voiceNoteLimitNotified = true;
                    this.voiceNoteNotification.add(
                        _t(
                            "The duration of voice notes is limited to %s second(s).",
                            maxDuration
                        ),
                        { type: "warning" }
                    );
                    this.voiceRecorder.onClick();
                }
            },
            () => [this.voiceRecorder?.elapsed, this.voiceRecorder?.recording]
        );

        // When captions are disabled, send as soon as the voice attachment is ready.
        useEffect(
            () => {
                if (session.mail_voice_note_allow_caption !== false) {
                    return;
                }
                const attachment = this.props.composer.voiceAttachment;
                if (!attachment || attachment.uploading || this._voiceNoteAutoSendPending) {
                    return;
                }
                this._voiceNoteAutoSendPending = true;
                Promise.resolve(this.sendMessage()).finally(() => {
                    this._voiceNoteAutoSendPending = false;
                });
            },
            () => [
                this.props.composer.voiceAttachment,
                this.props.composer.voiceAttachment?.uploading,
            ]
        );
    },

    async sendMessage() {
        const hadVoice = Boolean(this.props.composer.voiceAttachment);
        if (hadVoice && session.mail_voice_note_allow_caption === false) {
            // Keep the message body empty when captions are turned off.
            this.props.composer.composerText = "";
        }
        const result = await super.sendMessage(...arguments);
        // Composer.clear() runs only after a successful post.
        if (hadVoice && !this.props.composer.voiceAttachment) {
            this.voiceNoteNotification.add(_t("Audio note sent"), { type: "success" });
        }
        return result;
    },
});
