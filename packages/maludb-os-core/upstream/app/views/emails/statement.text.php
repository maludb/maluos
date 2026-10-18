<?php /** Statement email, text part. Data: $statement, $businessName */ ?>
Statement of account from <?= ($businessName ?? '') . "\n\n" ?>
<?php foreach (($statement['entries'] ?? []) as $entry): ?>
<?= $entry['entry_date'] ?>  <?= str_replace('_', ' ', $entry['kind']) ?>  <?= $entry['reference'] ?? '' ?>  <?= money($entry['amount'], $entry['currency']) . "\n" ?>
<?php endforeach; ?>
