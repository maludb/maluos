<?php /** Data: $name, $url */ ?>
<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#1b2431">
    <h2 style="color:#3454d1">Reset your password</h2>
    <p>Hi <?= e($name ?? 'there') ?>,</p>
    <p>We received a request to reset your MaluDb OS password. This link expires in one hour:</p>
    <p style="margin:24px 0">
        <a href="<?= e($url) ?>" style="background:#3454d1;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none">Reset password</a>
    </p>
    <p style="color:#6b7280;font-size:13px">If you didn't request this, you can safely ignore this email.</p>
</div>
