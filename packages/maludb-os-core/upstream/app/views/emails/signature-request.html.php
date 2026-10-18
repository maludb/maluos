<?php /** @var string $name @var string $subject @var string $message @var string $business @var ?string $sender @var string $link @var ?string $expiresAt */ ?>
<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#222;max-width:560px">
  <p>Hello <?= e($name) ?>,</p>
  <p><?= e($sender !== null && $sender !== '' ? $sender . ' at ' . $business : $business) ?> asks you to sign <strong><?= e($subject) ?></strong>.</p>
  <?php if ($message !== ''): ?><p style="white-space:pre-wrap;border-left:3px solid #ddd;padding-left:12px;color:#444"><?= e($message) ?></p><?php endif; ?>
  <p><a href="<?= e($link) ?>" style="display:inline-block;background:#3454d1;color:#fff;padding:10px 18px;border-radius:4px;text-decoration:none">Read and sign</a></p>
  <p style="font-size:13px;color:#666">This link is private to you — please do not forward it.<?php if ($expiresAt !== null): ?> It works until <?= e(gmdate('j F Y', (int) strtotime($expiresAt))) ?>.<?php endif; ?></p>
  <p style="font-size:13px;color:#666">If the button does not work, copy this address into your browser:<br><?= e($link) ?></p>
</div>
