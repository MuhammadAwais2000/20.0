/** @odoo-module **/

import { Chatter } from "@mail/chatter/web_portal_project/chatter";
import { _t } from "@web/core/l10n/translation";
import { session } from "@web/session";
import { patch } from "@web/core/utils/patch";

patch(Chatter.prototype, {
    /**
     * Mic is shown in the top bar for users allowed to record voice notes.
     * Visibility is driven by the session flag set in ir.http.session_info.
     */
    get canRecordVoiceNote() {
        // Prefer the dedicated group flag from session_info; fall back to any
        // internal user so the top-bar mic is not silently hidden when the
        // session cache is stale after install/upgrade.
        if (session.mail_voice_note_can_record) {
            return true;
        }
        return Boolean(session.is_internal_user);
    },

    get voiceNoteButtonTitle() {
        return _t("Voice Note");
    },

    /**
     * Open the Log note composer (not Send message) so voice notes stay
     * internal and do not pull in suggested partner_ids / recipients.
     * `startVoiceNote` on chatter state is observed by the Composer patch.
     */
    onClickVoiceNote() {
        if (!this.canRecordVoiceNote) {
            return;
        }
        this.state.startVoiceNote = true;
        if (this.state.composerType !== "note") {
            this.toggleComposer("note", { force: true });
        }
    },
});
