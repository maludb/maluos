# Vendored MaluOS Slides package

MaluOS Slides is the MaluOS presentation app: slides, slide shows and PowerPoint (.pptx) files,
native, with Malu, the assistant that edits the open deck through the app's own commands (a model
from Anthropic, OpenAI, Ollama or the MaluOS gateway; pictures from the office's image agent).
It is built from [maludb/maluos-slides](https://github.com/maludb/maluos-slides), which began as
a fork of DeckCraft (MIT OR Apache-2.0) and is developed independently since 2026-11-03. The
binary package is carried here so that the repository, image and CI builds are self-contained; a
Rust toolchain is not needed to build MaluOS. Refresh with
`scripts/vendor-maluos-slides-deb.sh <dir-with-debs>` after `packaging/linux/package.sh` in the
maluos-slides checkout (`dist/release/`); both local publishing (repo/publish.sh) and CI pick it
up from this directory. The desktop seed depends on `maluos-slides`, so every desktop image
installs it; the desktop entry sits in the Office category with Malu123, and `.pptx` files open
with it by double-click. The package also installs `maluos-slides-cli` (headless rendering, the
assistant, an MCP server and an HTTP/JSON API for agents).

| Package | Version | sha256 (prefix) |
|---|---|---|
| maluos-slides | 0.15.0-1 | 2abbc06da41aa082… |
