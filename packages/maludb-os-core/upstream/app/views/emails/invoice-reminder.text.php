<?php /** Invoice reminder, text part. Data: $invoice, $businessName, $message */ ?>
Reminder: invoice <?= ($invoice['number'] ?? '') ?> from <?= ($businessName ?? '') ?> is still open.

<?php if (!empty($message)): ?>
<?= $message . "\n\n" ?>
<?php endif; ?>
Outstanding: <?= money($invoice['balance_due'] ?? '0', $invoice['currency'] ?? 'USD') . "\n" ?>
Due: <?= ($invoice['due_date'] ?? '') . "\n" ?>
