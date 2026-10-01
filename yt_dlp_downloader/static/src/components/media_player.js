/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { Component, t, useProps } from "@odoo/owl";

export class YtDlpMediaPlayer extends Component {
    static template = "yt_dlp_downloader.MediaPlayer";
    props = useProps({
        ...standardWidgetProps,
    });

    get attachmentId() {
        const value = this.props.record.data.attachment_id;
        if (!value) {
            return false;
        }
        if (typeof value === "object") {
            return value.id || false;
        }
        if (Array.isArray(value)) {
            return value[0] || false;
        }
        return value;
    }

    get mimetype() {
        return this.props.record.data.mimetype || "";
    }

    get fileSize() {
        return this.props.record.data.file_size || 0;
    }

    get hasFile() {
        return Boolean(this.attachmentId) && this.fileSize > 0;
    }

    get fileSizeLabel() {
        const size = this.fileSize;
        if (!size) {
            return "";
        }
        if (size < 1024) {
            return `${size} B`;
        }
        if (size < 1024 * 1024) {
            return `${(size / 1024).toFixed(1)} KB`;
        }
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    }

    get title() {
        return this.props.record.data.name || this.props.record.data.file_name || _t("Media");
    }

    get isVideo() {
        return (this.mimetype || "").startsWith("video/");
    }

    get isAudio() {
        return (this.mimetype || "").startsWith("audio/");
    }

    get canPlay() {
        return this.hasFile && (this.isVideo || this.isAudio);
    }

    get mediaUrl() {
        if (!this.attachmentId) {
            return "";
        }
        // Unique query avoids browser cache of previous empty/404 responses.
        return `/web/content/${this.attachmentId}?download=false&unique=${this.fileSize}`;
    }
}

export const ytDlpMediaPlayer = {
    component: YtDlpMediaPlayer,
    fieldDependencies: [
        { name: "attachment_id", type: "many2one" },
        { name: "mimetype", type: "char" },
        { name: "file_size", type: "integer" },
        { name: "name", type: "char" },
        { name: "file_name", type: "char" },
    ],
};

registry.category("view_widgets").add("yt_dlp_media_player", ytDlpMediaPlayer);
