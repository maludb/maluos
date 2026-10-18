<?php /** Invoice email, text part. Data: $invoice, $lines, $businessName, $message */
$currency = $invoice['currency'] ?? 'USD'; ?>
Invoice <?= ($invoice['number'] ?? '') . "\n" ?>
From <?= ($businessName ?? '') . "\n\n" ?>
<?php if (!empty($message)): ?>
<?= $message . "\n\n" ?>
<?php endif; ?>
<?php foreach (($lines ?? []) as $line): ?>
<?= $line['description'] ?> — <?= rtrim(rtrim((string) $line['quantity'], '0'), '.') ?> x <?= money($line['unit_price'], $currency) ?> = <?= money($line['line_total'], $currency) . "\n" ?>
<?php endforeach; ?>

Total: <?= money($invoice['total'] ?? '0', $currency) . "\n" ?>
Due: <?= ($invoice['due_date'] ?? '') . "\n" ?>
