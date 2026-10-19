# Branding: what says MaluOS, what still says Ubuntu

MaluOS is built from Ubuntu packages, and Canonical's trademark policy
allows that for a derivative that does not present itself as Ubuntu. As of
maluos-branding 0.2.0 everything a user of an installed system sees names
MaluOS; the one remaining Ubuntu-branded surface is the installer program
on the ISO, listed at the end.

## Installed system

| Surface | Source | State |
|---|---|---|
| /usr/lib/os-release (NAME, PRETTY_NAME, ID=maluos, ID_LIKE="ubuntu debian", maluos.com URLs, VARIANT Server or Desktop, LOGO) | maluos-branding, diverting base-files' copy; a symlink to the variant's file since 0.3.0 | MaluOS |
| /etc/lsb-release, `lsb_release -a` | maluos-branding overwrites base-files' conffile | MaluOS |
| /etc/issue, /etc/issue.net (console and SSH banners) | maluos-branding | MaluOS |
| /etc/legal (login notice) | maluos-branding | MaluOS |
| Message of the day: header, help links, release-upgrade prompt, Pro and ESM prompts, motd-news | header reads os-release; the others are disabled; motd-news off | MaluOS only |
| GRUB menu entries (`GRUB_DISTRIBUTOR`) | /etc/default/grub.d/40-maluos.cfg | MaluOS |
| apt output: Ubuntu Pro and ESM advertising | the Pro client's apt hooks are diverted, its timers masked, apt_news off | none |
| Unattended upgrades | explicit origins (Ubuntu security archive, MaluOS repository) since `${distro_id}` is now MaluOS | works |
| Hostname default, autoinstall identity | maluos | MaluOS |
| /etc/maluos-release | maluos-branding | MaluOS 26.04 LTS |

Kept on purpose: `VERSION_CODENAME=resolute` and `UBUNTU_CODENAME=resolute`
in os-release, because apt suites and third-party install scripts key on
them, and `ID_LIKE=ubuntu`, which is how tools that know Ubuntu recognise a
derivative. Package names (`ubuntu-server-minimal`, `ubuntu-pro-client`)
and the `ubuntu.sources` file are machine-facing and stay. Neither is
trademark use.

`ID=maluos` is the change with reach: anything that compared `ID` to
`ubuntu` now sees a derivative and must use `ID_LIKE`. Known and handled:
unattended-upgrades (origins file above), GRUB (distributor set), the
installer's curtin (falls back to `ID_LIKE`). The image boot test checks
os-release, lsb_release, the banners, the motd, the GRUB menu and apt's
output on every build.

## Desktop (maluos-desktop-branding, Phase 12)

| Surface | Source | State |
|---|---|---|
| Login screen logo and background | gsettings override 20_maluos-desktop (org.gnome.login-screen logo, GNOME-Greeter background) | MaluOS |
| Session name in the greeter's chooser | ubuntu-session's wayland-sessions/ubuntu.desktop diverted, Name=MaluOS | MaluOS |
| Desktop and lock screen wallpaper | override for the `ubuntu` session class; wallpapers in /usr/share/backgrounds/maluos, listed in Settings > Appearance | MaluOS |
| Settings > About: name, logo | os-release PRETTY_NAME and LOGO=maluos-logo (hicolor icon) | MaluOS |
| Software Updater, release upgrader, ubuntu-report, whoopsie, Ubuntu docs | not installed (seeds/desktop.seed) | absent |
| Snap Store, Firefox and Chromium snaps | no snapd; GNOME Web is the browser | absent |
| Plymouth boot splash watermark | plymouth-theme-spinner's watermark.png links to Ubuntu's logo; diverted, MaluOS watermark, initramfs refreshed | MaluOS |
| Package and session mode names (`ubuntu-session`, `DesktopNames=ubuntu`, Yaru) | machine-facing | kept |

## Install media

| Surface | State |
|---|---|
| ISO volume label, GRUB boot menu, default entry | MaluOS; the interactive install is the default, the unattended entry is labelled and forces a password change at first login; the stock Ubuntu installer entry is gone |
| Installed result | the MaluOS root filesystem, branded as above (server or desktop) |
| The installer program itself (subiquity, the text UI during installation) | still Canonical's, shows "Ubuntu" in its screens |

The installer runs from Canonical's signed snap inside the live
environment; its strings cannot be changed without replacing the snap,
which the live image's seed validation refuses. Two ways out, both real
work: a trademark licence from Canonical for the installer screens, or a
MaluOS installer. The second is the durable answer (a small text installer
that partitions, unpacks the MaluOS squashfs and seeds first boot, which
is most of what we use subiquity for) and is proposed as a phase of its
own. Until one of them is done, the ISO is suitable for your own and
customers' machines under the trademark policy's "based on Ubuntu" terms
with the installer screens disclosed on the download page, and not yet for
a press release that calls it a new operating system.
