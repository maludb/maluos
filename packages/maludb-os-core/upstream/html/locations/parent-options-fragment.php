<?php
declare(strict_types=1);

/**
 * Pattern A fragment: the location form's `kind` select re-fetches this to swap in every field
 * that depends on the kind — siting, parent and (for a desk) owner. A building has neither
 * siting nor parent; an office picks a building (optional) and states siting; a desk picks the
 * office it sits in (required), states siting, and needs an owner (required). Gate: mod:locations, same as the form itself.
 *
 * The form sends its whole body with the request, so whatever the user has already chosen
 * survives a change of kind instead of being reset by the swap.
 */
require_once dirname(__DIR__, 2) . '/app/bootstrap.php';
require_once dirname(__DIR__, 2) . '/app/features/estate/render.php';

require_module_grant('locations');
estate_require_files();

$pdo = db();
$kind = request_string('kind', 'office');
$kind = in_array($kind, LOCATION_KINDS, true) ? $kind : 'office';

header('Vary: HX-Request');
echo view('estate/partials/parent-options.php', [
    'kind' => $kind,
    'siting' => request_string('siting') ?: null,
    'parentOptions' => parent_options($pdo, $kind),
    'selectedParent' => request_integer('parent_location_id'),
    'ownerOptions' => find_human_member_options($pdo),
    'selectedOwner' => request_integer('owner_member_id'),
]);
