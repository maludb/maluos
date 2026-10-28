<?php /** @var string $url @var string $inviter @var string $business @var string $company */ ?>
<p>Hello,</p>
<p><?= e($inviter) ?> at <?= e($business) ?> has opened the customer portal for you<?= $company !== '' ? ', for ' . e($company) : '' ?>. There you can see what we have shared with you and send us requests.</p>
<p><a href="<?= e($url) ?>">Set up your access</a></p>
<p style="color:#667">This link is tied to your email address and expires. If you were not expecting it, you can ignore this message.</p>
