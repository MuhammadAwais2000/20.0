import { composerActionsRegistry } from "@mail/core/common/composer_actions";
import { session } from "@web/session";

/**
 * Enable the built-in Discuss mic actions on every chatter thread
 * (not only discuss.channel), for users allowed to record voice notes.
 */
function canRecordVoice({ composer, owner }) {
    return Boolean(
        session.mail_voice_note_can_record &&
            composer.targetThread &&
            owner.voiceRecorder &&
            !composer.message
    );
}

const voiceStart = composerActionsRegistry.get("voice-start");
const voiceRecording = composerActionsRegistry.get("voice-recording");

voiceStart.condition = ({ composer, owner }) =>
    canRecordVoice({ composer, owner }) &&
    !owner.voiceRecorder.recording &&
    !composer.voiceAttachment;

voiceRecording.condition = ({ composer, owner }) =>
    canRecordVoice({ composer, owner }) && owner.voiceRecorder.recording;
