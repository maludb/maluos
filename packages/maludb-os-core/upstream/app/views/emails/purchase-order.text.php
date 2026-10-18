<?php /** @var array $order @var array $lines @var string $businessName @var string $message @var ?string $deliverTo */ ?>
Hello,

<?= $businessName ?> would like to order the following — purchase order <?= $order['po_number'] ?><?= !empty($order['expected_date']) ? ', needed by ' . $order['expected_date'] : '' ?>.

<?php if ($message !== ''): ?><?= $message ?>


<?php endif; ?>
<?php foreach ($lines as $l): ?>
- <?= ($l['sku'] ?? null) ? $l['sku'] . ' — ' . $l['description'] : $l['description'] ?>: <?= rtrim(rtrim((string) $l['quantity'], '0'), '.') ?> × <?= money((string) round((float) $l['unit_cost'], 2), (string) $order['currency']) ?> = <?= money((string) $l['line_total'], (string) $order['currency']) ?>

<?php endforeach; ?>

Tax: <?= money((string) $order['tax_total'], (string) $order['currency']) ?>

Total: <?= money((string) $order['total'], (string) $order['currency']) ?>

<?php if (!empty($deliverTo)): ?>
Deliver to: <?= $deliverTo ?>.
<?php endif; ?>

Please confirm the order and the delivery date with your usual contact at <?= $businessName ?> — this address is not read.
