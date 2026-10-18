<?php
/** Invoice email. Data: $invoice, $lines, $businessName, $message */
$invoice = $invoice ?? [];
$lines = $lines ?? [];
$businessName = $businessName ?? 'Business OS';
$message = $message ?? '';
$currency = $invoice['currency'] ?? 'USD';
?>
<p>Invoice <strong><?= e($invoice['number'] ?? '') ?></strong> from <?= e($businessName) ?>.</p>
<?php if ($message !== ''): ?><p><?= nl2br(e($message)) ?></p><?php endif; ?>
<table cellpadding="6" cellspacing="0" border="0" style="border-collapse:collapse;width:100%">
    <tr style="background:#f5f5f5">
        <th align="left">Description</th><th align="right">Qty</th>
        <th align="right">Unit price</th><th align="right">Total</th>
    </tr>
    <?php foreach ($lines as $line): ?>
        <tr>
            <td><?= e($line['description']) ?></td>
            <td align="right"><?= e(rtrim(rtrim((string) $line['quantity'], '0'), '.')) ?></td>
            <td align="right"><?= e(money($line['unit_price'], $currency)) ?></td>
            <td align="right"><?= e(money($line['line_total'], $currency)) ?></td>
        </tr>
    <?php endforeach; ?>
    <tr><td colspan="3" align="right"><strong>Total</strong></td>
        <td align="right"><strong><?= e(money($invoice['total'] ?? '0', $currency)) ?></strong></td></tr>
    <tr><td colspan="3" align="right">Due</td>
        <td align="right"><?= e($invoice['due_date'] ?? '') ?></td></tr>
</table>
<?php if (($invoice['terms'] ?? '') !== ''): ?><p style="color:#666"><?= nl2br(e($invoice['terms'])) ?></p><?php endif; ?>
