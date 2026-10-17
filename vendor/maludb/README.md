# Vendored MaluDB engine packages

Binary packages built from [maludb/maludb-core-26](https://github.com/maludb/maludb-core-26)
(Ubuntu 26.04, PostgreSQL 18), carried here so that the repository, image and
CI builds are self-contained. Refresh with `scripts/vendor-maludb-debs.sh <dir-with-debs>`
after building a new maludb-core-26 release; both local publishing
(repo/publish.sh) and CI pick them up from this directory.

| Package | Version |
|---|---|
| postgresql-18-maludb-core | 0.106.0-1 |
| maludb-mc2dbd | 0.106.0-1 |
