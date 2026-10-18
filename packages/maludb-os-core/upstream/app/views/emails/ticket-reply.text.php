<?php /** @var string $number @var string $subject @var string $body @var string $from @var string $business @var ?string $portalUrl */ ?>
Hello,

<?= $from ?> at <?= $business ?> replied to your request <?= $number ?> — <?= $subject ?>:

<?= $body ?>


<?php if (!empty($portalUrl)): ?>
Read the whole conversation and answer here: <?= $portalUrl ?>
<?php else: ?>
Please do not reply to this email — it is sent from an address that is not read.
<?php endif; ?>
