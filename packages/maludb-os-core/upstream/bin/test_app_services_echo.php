<?php
/**
 * A fake provider MCP server for bin/test_app_services.php's K26 block: `php -S 127.0.0.1:8097 bin/test_app_services_echo.php`.
 * Streamable HTTP, plain JSON: initialize → a result; tools/call → the tool's arguments and the request's X-OS-* headers echoed back
 * as structuredContent; an argument `sleep` (seconds) delays the answer so the share's timeout can be proven. Admits any bearer.
 */
header('Content-Type: application/json');
$in = json_decode((string) file_get_contents('php://input'), true) ?: [];
$id = $in['id'] ?? null;
$method = (string) ($in['method'] ?? '');
if ($method === 'initialize') {
    header('Mcp-Session-Id: echo-' . bin2hex(random_bytes(4)));
    echo json_encode(['jsonrpc' => '2.0', 'id' => $id, 'result' => ['protocolVersion' => '2025-06-18', 'capabilities' => ['tools' => (object) []], 'serverInfo' => ['name' => 'echo', 'version' => '1']]]);
    exit;
}
if ($method === 'tools/call') {
    $args = (array) ($in['params']['arguments'] ?? []);
    if (isset($args['sleep'])) {
        sleep((int) $args['sleep']);
    }
    $seen = ['tool' => $in['params']['name'] ?? '', 'arguments' => $args,
             'consumer' => $_SERVER['HTTP_X_OS_CONSUMER'] ?? null, 'consumer_agent' => $_SERVER['HTTP_X_OS_CONSUMER_AGENT'] ?? null,
             'bearer' => str_starts_with((string) ($_SERVER['HTTP_AUTHORIZATION'] ?? ''), 'Bearer kernel.') ? 'kernel' : 'other'];
    echo json_encode(['jsonrpc' => '2.0', 'id' => $id, 'result' => ['content' => [['type' => 'text', 'text' => json_encode($seen)]], 'structuredContent' => $seen]]);
    exit;
}
http_response_code(202);
