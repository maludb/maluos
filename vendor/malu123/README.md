# Vendored Malu123 package

Malu123 is the MaluOS spreadsheet: Excel-compatible, native, with an LLM assistant on the way.
It is built from [maludb/malu123](https://github.com/maludb/malu123), a fork of GridCraft
(MIT OR Apache-2.0). The binary package is carried here so that the repository, image and CI
builds are self-contained; a Rust toolchain is not needed to build MaluOS. Refresh with
`scripts/vendor-malu123-deb.sh <dir-with-debs>` after `packaging/linux/package.sh` in the
malu123 checkout; both local publishing (repo/publish.sh) and CI pick it up from this directory.
The desktop seed depends on `malu123`, so every desktop image installs it. `malu123-web` is the
browser build (WebAssembly, a static site under `/usr/share/malu123-web`) that enables `/malu123/`
on Apache where it is installed; the business-os seed recommends it, so the server edition serves
the spreadsheet to every browser on the office network.

| Package | Version | sha256 (prefix) |
|---|---|---|
| malu123 | 0.11.1-1 | 146f201e70beb0f2… |
| malu123-web | 0.11.1-1 | 4ed1b06f72036eda… |
