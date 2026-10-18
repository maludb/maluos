<?php /** @var string $name @var string $subject @var string $message @var string $business @var ?string $sender @var string $link @var ?string $expiresAt */ ?>
Hello <?= $name ?>,

<?= $sender !== null && $sender !== '' ? $sender . ' at ' . $business : $business ?> asks you to sign "<?= $subject ?>".
<?php if ($message !== ''): ?>

<?= $message ?>

<?php endif; ?>

Read and sign: <?= $link ?>


This link is private to you - please do not forward it.<?php if ($expiresAt !== null): ?> It works until <?= gmdate('j F Y', (int) strtotime($expiresAt)) ?>.<?php endif; ?>

