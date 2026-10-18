`maluos-archive-keyring.asc` is the ASCII-armoured public archive key,
exported by `repo/init.sh`. Never commit a private key here.

Every `*.asc` here is imported into the shipped keyring
(/usr/share/keyrings/maluos-archive-keyring.gpg), so a production key made
with `repo/make-production-key.sh YEAR` sits beside the development key and
rotation is: add the new public key, publish the keyring signed by the old
key, switch MALUOS_SIGNING_UID, later remove the old key.

