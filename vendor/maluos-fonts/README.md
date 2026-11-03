# Vendored MaluOS fonts package

`maluos-fonts` carries the presentation and document fonts the MaluOS office apps render with:
the Latin presentation faces (Inter, Lato, Montserrat, Merriweather, ...), the Office-metric
substitutes (Carlito, Caladea, Liberation), and the Japanese, Simplified Chinese, Korean, Arabic,
Hebrew, Devanagari, Georgian and symbol faces, all under the SIL Open Font License, from
storytold/craft-fonts' reviewed catalogue (the package's `copyright` lists every face with its
source). They install under `/usr/share/fonts/truetype/maluos-fonts/`, where MaluOS Slides finds
them at run time (so its own package no longer embeds 80 MB of fonts in each binary), and where
Malu123 and MaluDocs render with the same faces. Built by `packaging/linux/fonts-package.sh` in
the [maludb/maluos-slides](https://github.com/maludb/maluos-slides) checkout from a craft-fonts
checkout; the version is the craft-fonts commit date. Refresh with
`scripts/vendor-maluos-fonts-deb.sh <dir-with-debs>`. The desktop seed depends on it.

| Package | Version | sha256 (prefix) |
|---|---|---|
| maluos-fonts | 2026.10.25-1 | 5843eaf519b52741… |
