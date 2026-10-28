<?php /** Quote email, text part. Data: $quote, $lines, $businessName, $message */
$currency = $quote['currency'] ?? 'USD'; ?>
Quote <?= ($quote['number'] ?? '') . "\n" ?>
From <?= ($businessName ?? '') . "\n\n" ?>
<?php if (!empty($message)): ?>
<?= $message . "\n\n" ?>
<?php endif; ?>
<?php foreach (($lines ?? []) as $line): ?>
<?= $line['description'] ?> — <?= rtrim(rtrim((string) $line['quantity'], '0'), '.') ?> x <?= money($line['unit_price'], $currency) ?> = <?= money($line['line_total'], $currency) . "\n" ?>
<?php endforeach; ?>

Total: <?= money($quote['total'] ?? '0', $currency) . "\n" ?>
<?php if (!empty($quote['valid_until'])): ?>
Valid until: <?= $quote['valid_until'] . "\n" ?>
<?php endif; ?>
