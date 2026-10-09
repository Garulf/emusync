#!/usr/bin/env bash
. "$HOME/.config/EmuDeck/backend/functions/all.sh"
emulatorInit "mgba"
flatpak run io.mgba.mGBA "${@}"
