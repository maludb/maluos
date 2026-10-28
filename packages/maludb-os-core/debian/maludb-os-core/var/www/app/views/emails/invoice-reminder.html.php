<?php
/** Invoice reminder email. Data: $invoice, $businessName, $message */
$invoice = $invoice ?? [];
$businessName = $businessName ?? 'Business OS';
$message = $message ?? '';
?>
<p>A reminder that invoice <strong><?= e($invoice['number'] ?? '') ?></strong>
   from <?= e($businessName) ?> is still open.</p>
<?php if ($message !== ''): ?><p><?= nl2br(e($message)) ?></p><?php endif; ?>
<p>Amount outstanding: <strong><?= e(money($invoice['balance_due'] ?? '0', $invoice['currency'] ?? 'USD')) ?></strong><br>
   Due: <?= e($invoice['due_date'] ?? '') ?></p>
