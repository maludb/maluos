<?php /** Data: $url, $inviter, $message?, $role */ ?>
You're invited to MaluDb OS

<?= ($inviter ?? 'An organizer') ?> invited you to join the community for studying
the Anthropic Claude certification exams<?= ($role ?? 'member') === 'organizer' ? ' as an organizer' : '' ?>.

<?php if (!empty($message)): ?>
"<?= $message ?>"

<?php endif; ?>
Accept your invitation:
<?= $url . "\n" ?>

This invitation link is tied to your email address and will expire.
