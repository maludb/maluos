<?php /** Data: $name, $url */ ?>
Reset your password

Hi <?= ($name ?? 'there') . "\n" ?>

We received a request to reset your MaluDb OS password.
This link expires in one hour:

<?= $url . "\n" ?>

If you didn't request this, you can safely ignore this email.
