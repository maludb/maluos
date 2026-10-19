# Autoinstall configurations

Subiquity autoinstall (cloud-init NoCloud) data placed on the ISO under
`/maluos/nocloud-<variant>/`. `iso/build-iso.sh` renders the templates:

| Template | ISO menu entry | Behaviour |
|---|---|---|
| server-auto.yaml | Install MaluOS Server (automated, erases first disk) | Fully unattended: LVM on the first disk, user `maluos`, hostname `maluos` |
| server-interactive.yaml | Install MaluOS Server | Normal installer screens for locale, network, storage, identity and SSH; MaluOS packages installed automatically afterwards |

Placeholders: `@AUTHORIZED_KEYS@` (SSH keys injected by `--ssh-key`).

Default credentials of the automated variant are `maluos` / `maluos`.
Change them on first login; the ISO is not meant for exposed networks as is.

Both variants share the same `late-commands.yaml`: copy the MaluOS
repository from the ISO to `/var/lib/maluos/apt` for later installs. Then
a profile tail (`late-commands-server.yaml`: serial console;
`late-commands-desktop.yaml`: quiet splash) and a variant tail
(`late-commands-auto.yaml`: force a password change) are appended.

The same templates serve the desktop ISO (`iso/build-iso.sh -p desktop`):
the install source id becomes `maluos-desktop` and the menu says
"Install MaluOS Desktop"; the installer screens are the same text UI.
