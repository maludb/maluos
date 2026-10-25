# Vendored Apple T2 packages

Binary packages from the t2linux project's Ubuntu repository
([AdityaGarg8/t2-ubuntu-repo](https://github.com/AdityaGarg8/t2-ubuntu-repo),
the common pool and the `resolute` release pool), carried here so that the
repository, the medium and CI are self-contained and offline installs on a
Mac get them from the medium. They are the `apple-t2` component's parts that
MaluOS does not build itself (two Rust daemons, three DKMS sources, two sets
of configuration files, one script). The T2 bridge driver itself is built
from source in packages/apple-bce-dkms. Refresh by downloading the newer
files, checking them against the repository's `Packages` index and updating
this table; both repo/publish.sh and ci/build-flat-repo.sh pick up
`vendor/*/*.deb`.

| Package | Version | Role | Licence | sha256 |
|---|---|---|---|---|
| apple-t2-audio-config | 0.5.3-resolute | ALSA UCM profiles for the T2 audio device (AppleT2x2/x4/x6) | GPL-2+ | c2f6a8951dd3a2683f456d2bfbd1349f9664ceb214fa0c6e0d37fb495449a4d1 |
| applesmc-t2 | 0.1.5 | DKMS: the SMC driver patched for T2 Macs (fans, temperatures, keyboard backlight) | GPL-2 | cac368bfe774b100962144c5048f0e6eff1b8b0206d2c3cfc9220cbf64be22a4 |
| bcm5974-t2 | 0.1.3 | DKMS: the trackpad driver patched for the T2 Macs' USB ids (multitouch gestures) | GPL-2 | aea61df624bf691df78b7249071573c03b26d7a71ce190e54c0cb039cec32420 |
| apfs-dkms | 0.3.22-2 | DKMS: linux-apfs-rw, reads the macOS volumes (the firmware import from a macOS install) | GPL-2 | 5909e31c2618dd30c8d8d3643e3c4322e7348815ef8870ff9bcb9d79d0227c9f |
| tiny-dfr | 0.3.8-1-resolute | the Touch Bar function-row daemon (Rust) | MIT | 0e69b3b9620091493098716bb812e8538afd058468a2bdf2bb5394a9e314aed1 |
| t2fanrd | 0.1.0-4 | the fan curve daemon (Rust) | MIT | bc3ce5ca337fbb365a4676560872fa4cbe2cb124e1c3d5f0758ac98e90db14c0 |
| t2-dsp | 0.2.0-2 | PipeWire speaker and microphone graphs per model | GPL-3+ | 927ff3e839a95fb1c44d28ad219570ab9be2359df0916107d38821611eddeb4d |
| apple-firmware-script | 1.4-3 | `get-apple-firmware`: the five ways to fetch the Broadcom Wi-Fi and Bluetooth firmware | MIT | b6b8729afe3183378dee2f232f9311bad00d5e2646df280d0cbd3df22d58d0c6 |

The firmware itself is Apple's and is never on the medium: the installer
imports it from the Mac (docs/phase11-apple-t2.md).
