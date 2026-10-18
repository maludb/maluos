<?php
declare(strict_types=1);

require_once dirname(__DIR__, 3) . '/app/bootstrap.php';

header('Cache-Control: no-store');

if (!google_enabled()) {
    redirect('/login.php');
}

$provider = new League\OAuth2\Client\Provider\Google([
    'clientId'     => (string) env('GOOGLE_CLIENT_ID'),
    'clientSecret' => (string) env('GOOGLE_CLIENT_SECRET'),
    'redirectUri'  => (string) env('GOOGLE_REDIRECT_URI', app_url('/auth/google/callback')),
]);

$authUrl = $provider->getAuthorizationUrl([
    'scope' => ['openid', 'email', 'profile'],
]);

// State is the CSRF guard for the OAuth flow; store it (and where to go next) in the session.
$_SESSION['oauth2state'] = $provider->getState();
$_SESSION['oauth2next']  = safe_next(request_string('next', '/'));

redirect($authUrl);
