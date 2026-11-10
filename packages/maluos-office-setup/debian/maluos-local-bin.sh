# maluos-office-setup: Claude Code is installed per user in ~/.local/bin (Anthropic's installer). The login
# profile adds that directory only when it already exists at login; this adds it always, so `claude` is found
# in the first shell opened after `maluctl office-setup` installed it.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) [ -n "${HOME:-}" ] && PATH="$HOME/.local/bin:$PATH" ;; esac
