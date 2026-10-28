<?php /** Data: $url, $inviter, $message?, $role */ ?>
<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#1b2431">
    <h2 style="color:#3454d1">You're invited to MaluDb OS</h2>
    <p><?= e($inviter ?? 'An organizer') ?> invited you to join the community for studying the Anthropic Claude certification exams<?= ($role ?? 'member') === 'organizer' ? ' as an organizer' : '' ?>.</p>
    <?php if (!empty($message)): ?>
        <blockquote style="border-left:3px solid #3454d1;margin:16px 0;padding:4px 16px;color:#374151"><?= e($message) ?></blockquote>
    <?php endif; ?>
    <p style="margin:24px 0">
        <a href="<?= e($url) ?>" style="background:#3454d1;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none">Accept invitation</a>
    </p>
    <p style="color:#6b7280;font-size:13px">This invitation link is tied to your email address and will expire.</p>
</div>
