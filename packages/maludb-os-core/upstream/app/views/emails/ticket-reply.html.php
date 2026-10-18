<?php /** @var string $number @var string $subject @var string $body @var string $from @var string $business @var ?string $portalUrl */ ?>
<p>Hello,</p>
<p><?= e($from) ?> at <?= e($business) ?> replied to your request <strong><?= e($number) ?> — <?= e($subject) ?></strong>:</p>
<blockquote style="border-left:3px solid #ccd; margin:12px 0; padding:4px 12px; white-space:pre-wrap;"><?= e($body) ?></blockquote>
<?php if (!empty($portalUrl)): ?>
<p>You can read the whole conversation and answer here: <a href="<?= e($portalUrl) ?>"><?= e($portalUrl) ?></a></p>
<?php else: ?>
<p>Please do not reply to this email — it is sent from an address that is not read.</p>
<?php endif; ?>
