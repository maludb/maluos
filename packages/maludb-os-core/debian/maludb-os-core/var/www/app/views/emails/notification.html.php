<?php /** Data: $title, $body, $url */ ?>
<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;color:#1b2431">
    <h2 style="color:#3454d1;font-size:18px"><?= e($title) ?></h2>
    <?php if (!empty($body)): ?><p><?= e($body) ?></p><?php endif; ?>
    <?php if (!empty($url)): ?>
        <p style="margin:24px 0"><a href="<?= e($url) ?>" style="background:#3454d1;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Open in MaluDb OS</a></p>
    <?php endif; ?>
    <p style="color:#6b7280;font-size:12px">You can adjust which emails you receive in Settings.</p>
</div>
