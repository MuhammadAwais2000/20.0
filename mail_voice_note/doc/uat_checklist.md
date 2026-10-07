# Voice Notes in Chatter — UAT checklist

## Setup
- [ ] Module `mail_voice_note` installs without errors
- [ ] Settings → Discuss shows **Voice Note Duration** and **Allow Audio Captions**
- [ ] Internal users have group **Record Voice Notes**

## Recording
- [ ] Mic action appears on a contact / CRM form chatter
- [ ] Mic action appears in Discuss channels
- [ ] Users without the group do not see the mic
- [ ] Recording shows elapsed time and waveform
- [ ] Recording auto-stops at the configured max duration
- [ ] Cancel discards the in-progress recording

## Captions enabled
- [ ] After stop, voice attachment appears with player
- [ ] Optional text can be typed before Send
- [ ] Send posts the note; toast **Audio note sent** appears
- [ ] Message shows playable voice note; download works

## Captions disabled
- [ ] After stop, note is sent automatically
- [ ] Toast **Audio note sent** appears

## Permissions / browser
- [ ] Microphone permission denied shows Odoo’s permission dialog
- [ ] HTTPS or localhost is used (required by browsers for mic access)
