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

Both variants share the same `late-commands`: copy the MaluOS repository
from the ISO to `/var/lib/maluos/apt`, enable PGDG, install `maluos-server`,
then disable the network MaluOS source until public hosting exists.
