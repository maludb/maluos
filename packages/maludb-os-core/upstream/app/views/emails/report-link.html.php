<?php /** @var string $name @var string $report @var string $says @var string $url @var string $business */ ?>
<p>Hello <?= e($name) ?>,</p>
<p>Your scheduled report <strong><?= e($report) ?></strong> (<?= e($says) ?>) is ready at <?= e($business) ?>:</p>
<p><a href="<?= e($url) ?>"><?= e($url) ?></a></p>
<p style="color:#667;">The link opens the report for you, signed in as yourself — it shows what you are allowed to see, as of the moment you open it. No figures are in this email.</p>
