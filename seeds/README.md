# Seeds

One package per line. Blank lines and `#` comments are ignored.
A line beginning with `?` is a Recommends rather than a Depends.

Each `<name>.seed` becomes the metapackage `maluos-<name>`; run
`scripts/gen-meta-control.sh` to regenerate `packages/maluos-meta/debian/control`
(the build script does this automatically).
