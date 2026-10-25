# telemetry.maluos.com

The MaluOS installer sends one JSON report per install, at the end and on a
failure, only when the plan says `telemetry: {send: true}` (the media's
unattended plans say false; `maluos-install --telemetry-preview --plan …`
prints the document). The document and its rules are in
docs/phase11-slice2-engine.md ("The telemetry report and endpoint"); the
Worker here is the endpoint: `POST /v1/install`, body at most 32 KB with
`v: 1`, 60 requests per minute per address, the address dropped and the
country code kept, each report written to the R2 bucket `maluos-telemetry`
as `install/YYYY/MM/DD/<install_id>.json`, a 204 and nothing else.

Deploy (the owner's Cloudflare account): create the bucket, set a lifecycle
rule deleting objects after 730 days, `wrangler deploy` from this directory,
attach the custom domain. The daily count by release, variant, layout and
firmware is a later job, once the first reports exist.
