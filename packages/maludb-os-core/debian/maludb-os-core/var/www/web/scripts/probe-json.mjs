// What PHP answers a member, as JSON — for shaping a schema or checking a gate without a browser.
// Usage: scripts/verify.sh <member> --probe scripts/probe-json.mjs <php-path> [<php-path>…]   (paths as web/lib/api.ts would ask them)
const [sid, ...paths] = process.argv.slice(2);
for (const path of paths) {
  const res = await fetch(`http://127.0.0.1:8080${path}`, { headers: { Accept: "application/json", Cookie: `CSTSID=${sid}` }, redirect: "manual" });
  const text = await res.text();
  console.log(`${res.status} ${path}\n  ${text.slice(0, Number(process.env.CHARS ?? 700))}`);
}
