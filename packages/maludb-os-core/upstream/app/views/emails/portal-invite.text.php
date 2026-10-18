<?php /** Data: $url, $inviter, $business, $company */ ?>
Hello,

<?= $inviter ?> at <?= $business ?> has opened the customer portal for you<?= $company !== '' ? ', for ' . $company : '' ?>.
There you can see what we have shared with you and send us requests.

Set up your access:
<?= $url . "\n" ?>

This link is tied to your email address and expires. If you were not expecting it, you can ignore this message.
