<?php
/** Statement email. Data: $statement, $businessName */
$statement = $statement ?? [];
$businessName = $businessName ?? '';
$entries = $statement['entries'] ?? [];
?>
<p>Statement of account from <?= e($businessName) ?>.</p>
<table cellpadding="6" cellspacing="0" border="0" style="border-collapse:collapse;width:100%">
    <tr style="background:#f5f5f5"><th align="left">Date</th><th align="left">What</th>
        <th align="left">Reference</th><th align="right">Amount</th></tr>
    <?php foreach ($entries as $entry): ?>
        <tr>
            <td><?= e($entry['entry_date']) ?></td>
            <td><?= e(str_replace('_', ' ', $entry['kind'])) ?></td>
            <td><?= e($entry['reference'] ?? '') ?></td>
            <td align="right"><?= e(money($entry['amount'], $entry['currency'])) ?></td>
        </tr>
    <?php endforeach; ?>
</table>
