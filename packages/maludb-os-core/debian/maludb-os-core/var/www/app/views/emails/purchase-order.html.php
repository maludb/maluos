<?php /** @var array $order @var array $lines @var string $businessName @var string $message @var ?string $deliverTo */ ?>
<p>Hello,</p>
<p><?= e($businessName) ?> would like to order the following — purchase order <strong><?= e((string) $order['po_number']) ?></strong><?= !empty($order['expected_date']) ? ', needed by ' . e((string) $order['expected_date']) : '' ?>.</p>
<?php if ($message !== ''): ?><p style="white-space:pre-wrap;"><?= e($message) ?></p><?php endif; ?>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse; border:1px solid #dde;">
  <tr style="background:#f4f5f8;"><th align="left">Item</th><th align="right">Quantity</th><th align="right">Unit cost</th><th align="right">Total</th></tr>
<?php foreach ($lines as $l): ?>
  <tr style="border-top:1px solid #dde;">
    <td><?= e(($l['sku'] ?? null) ? $l['sku'] . ' — ' . $l['description'] : (string) $l['description']) ?></td>
    <td align="right"><?= e(rtrim(rtrim((string) $l['quantity'], '0'), '.')) ?></td>
    <td align="right"><?= e(money((string) round((float) $l['unit_cost'], 2), (string) $order['currency'])) ?></td>
    <td align="right"><?= e(money((string) $l['line_total'], (string) $order['currency'])) ?></td>
  </tr>
<?php endforeach; ?>
  <tr style="border-top:1px solid #dde;"><td colspan="3" align="right">Tax</td><td align="right"><?= e(money((string) $order['tax_total'], (string) $order['currency'])) ?></td></tr>
  <tr><td colspan="3" align="right"><strong>Total</strong></td><td align="right"><strong><?= e(money((string) $order['total'], (string) $order['currency'])) ?></strong></td></tr>
</table>
<?php if (!empty($deliverTo)): ?><p>Deliver to: <?= e($deliverTo) ?>.</p><?php endif; ?>
<p>Please confirm the order and the delivery date with your usual contact at <?= e($businessName) ?> — this address is not read.</p>
