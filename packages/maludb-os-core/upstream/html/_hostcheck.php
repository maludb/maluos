<?php
// TEMPORARY diagnostic (2026-09-18) — delete once the cookie domain is confirmed.
// Shows only how this request's host/proto arrived through the reverse proxy. No session
// data, no secrets, no database. Deliberately reveals nothing a visitor could not infer.
header('Content-Type: text/plain; charset=utf-8');
$keys = ['HTTP_HOST', 'HTTP_X_FORWARDED_HOST', 'HTTP_X_FORWARDED_PROTO',
         'HTTP_X_FORWARDED_FOR', 'SERVER_NAME', 'HTTPS', 'REQUEST_SCHEME'];
foreach ($keys as $k) {
    printf("%-24s %s\n", $k, isset($_SERVER[$k]) ? (string) $_SERVER[$k] : '(absent)');
}
echo str_repeat('-', 50), "\n";
echo "cookie header present:   ", isset($_SERVER['HTTP_COOKIE']) ? 'yes' : 'NO', "\n";
echo "CSTSID cookie present:   ", isset($_COOKIE['CSTSID']) ? 'yes' : 'NO', "\n";
