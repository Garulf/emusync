#!/usr/bin/env bash
emuName="citron" #parameterize me
cd "$HOME/.config/EmuDeck/backend/"
git pull
. "$HOME/.config/EmuDeck/backend/functions/all.sh"
launcherInit
emulatorInit "$emuName"
"$HOME/Applications/citron.AppImage" "${@}"
cloud_sync_uploadForced
rm -rf "$savesPath/.gaming";
