# The three deployment topologies

What the office's web scheme is, where TLS ends, and what each name must resolve to. The SSH
management route is a separate matter (handbook 10-office-first-login-and-ssh.md); none of this
changes it.

| | A: external HTTPS proxy | B: private network, HTTP | C: direct TLS on the office |
|---|---|---|---|
| `scheme` in firstboot.yaml | `https` | `http` | would be `https` |
| Where TLS ends | the nginx proxy in front (its certificates) | nowhere; plain HTTP on the LAN | on the office's Apache |
| What the proxy needs | one server block per name, `Host` passed through, `X-Forwarded-Proto https`, long read timeouts, no buffering on the kernel's names; see `proxy-config.sh` | no proxy | no proxy |
| How clients resolve the names | LAN DNS (and public DNS if wanted) to the proxy | LAN DNS or hosts files to the office's stable address | public or LAN DNS to the office |
| How the office resolves its own names | **to the proxy's LAN address**: nothing on the office answers :443, so loopback breaks every self-call (sign-on hand-off, application health). Native since maluos-firstboot 0.1.16 (`proxy_address`); `hosts-proxy.sh` before that | to loopback, which first boot writes | to loopback, if the office served TLS |
| Supported by this plugin | **yes**, the worked deployment of the handbook | **yes**, with the LAN DNS as the operator's item; no TLS, so for a private network only | **no**: no certificate issuance, renewal or TLS listener exists on the office in this release. Offer A or B |

## Choosing

- A reverse proxy that already fronts the LAN, or a hosting setup where the public address belongs to a
  proxy host: **A**. This is the topology every later stage of the handbook was run on.
- A physical server on an office LAN with no public exposure wanted: **B**. Say clearly that traffic is
  unencrypted on the LAN and that the kernel sets non-secure cookies under http.
- A VM with its own public address and no proxy: the operator wants **C**. Until the office can
  terminate TLS itself, the honest options are a small nginx in front on the same host or network (then
  A, with the proxy address being that nginx's address as the office reaches it) or B behind a VPN.

## The addresses that get confused (topology A)

| Name in the questions | What it is | Example |
|---|---|---|
| Business domain | the names people type | `example.com`, `app.example.com` |
| Proxy address | the proxy as **the office** reaches it; goes into the office's `/etc/hosts` | `192.168.100.1` |
| Office upstream | the office as **the proxy** reaches it; goes into the proxy's `upstream` | `192.168.100.50:80` |
| SSH management address | where the operator's SSH lands; often the same as the upstream, never the proxy's web port | `192.168.100.50:22` |

A dedicated public IP on the office supplies reachability only. It does not make the HTTP proxy carry
SSH, and it does not give the office a certificate.
