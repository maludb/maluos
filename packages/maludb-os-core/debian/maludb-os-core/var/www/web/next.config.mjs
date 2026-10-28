/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    // A form that uploads a file is a server action like any other (lib/api.ts sends it to PHP
    // as multipart). Next.js stops an action's body at 1 MB by default; 27 MB matches PHP's
    // post_max_size, set for the Documents module's 25 MB uploads (owner, 2026-09-19 — see
    // docs/deploy/php-99-business-os.ini). Each feature still enforces its own ceiling in PHP:
    // an agent photo stays 2 MB.
    serverActions: { bodySizeLimit: "27mb" },
  },
  // Links in mail that has already been sent name the PHP pages (forgot.php and the invitation
  // handlers build `/reset.php?token=…` and `/register.php?token=…`), and people have the old
  // sign-in page bookmarked. Once this app is the front door those addresses must still land —
  // the query string travels with a redirect unasked. Permanent (308) since the cut-over of
  // 2026-09-19; docs/react-cutover-runbook.md.
  async redirects() {
    return [
      // A name that is neither os.<domain> nor app.<domain> (the bare domain, the retired staging name) is
      // sent on to app.<domain> by the middleware (lib/face.ts), since the names are configuration.
      { source: "/reset.php", destination: "/reset", permanent: true },
      { source: "/register.php", destination: "/register", permanent: true },
      { source: "/forgot.php", destination: "/forgot", permanent: true },
      { source: "/login.php", destination: "/login", permanent: true },
    ];
  },
};

export default nextConfig;
