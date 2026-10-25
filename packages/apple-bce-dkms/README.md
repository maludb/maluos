# apple-bce-dkms

The t2linux `apple-bce` driver (https://github.com/t2linux/apple-bce-drv,
branch `aur`, commit c7448ca, 2026-06-24) as a DKMS package. The source
under `apple-bce-0.2.9+git20260624.c7448ca/` is the upstream tree unchanged (the .o files
dropped) plus `dkms.conf`. To refresh: clone the branch, copy the C sources,
the headers and the Makefile over, bump the version in the directory name,
`dkms.conf`, `debian/install` and `debian/changelog`, and build it once
against the current kernel (`make KVERSION=$(uname -r)`) before the
package build.
