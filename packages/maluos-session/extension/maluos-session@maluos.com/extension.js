// MaluOS Session: the top-panel indicator for an agent-aware desk.
// All state comes from maluos-desktop-session (com.maluos.Session on the
// session bus); this file only renders it and forwards agent actions.
import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'com.maluos.Session';
const OBJECT_PATH = '/com/maluos/Session';
const IFACE_XML = `<node>
<interface name="com.maluos.Session1">
  <method name="GetState"><arg type="s" name="json" direction="out"/></method>
  <method name="Refresh"/>
  <method name="AgentAction"><arg type="s" name="name" direction="in"/><arg type="s" name="action" direction="in"/></method>
  <method name="RequestDecide"><arg type="i" name="id" direction="in"/><arg type="s" name="decision" direction="in"/><arg type="s" name="expires" direction="in"/><arg type="s" name="json" direction="out"/></method>
  <method name="UpdateAction"><arg type="s" name="action" direction="in"/></method>
  <method name="OfficeAction"><arg type="s" name="action" direction="in"/></method>
  <signal name="StateChanged"><arg type="s" name="json"/></signal>
  <property name="Version" type="s" access="read"/>
</interface>
</node>`;
const SessionProxy = Gio.DBusProxy.makeProxyWrapper(IFACE_XML);

const DOT = {active: '●', activating: '◐', deactivating: '◐', reloading: '◐', inactive: '○', failed: '●'};
const DOT_CLASS = {active: 'maluos-dot-ok', activating: 'maluos-dot-warn', deactivating: 'maluos-dot-warn', reloading: 'maluos-dot-warn',
    inactive: 'maluos-dot-off', failed: 'maluos-dot-bad'};

function usd(v) {
    return v === null || v === undefined ? '?' : `$${Number(v).toFixed(2)}`;
}

function hhmm(ts) {
    if (!ts)
        return '';
    const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
    return isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
}

function spawn(argv) {
    try {
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
    } catch (e) {
        Main.notify('MaluOS', `could not run ${argv[0]}: ${e.message}`);
    }
}

// A non-reactive line of text in the menu, optionally dimmed.
class InfoItem extends PopupMenu.PopupBaseMenuItem {
    static {
        GObject.registerClass(this);
    }

    _init(text, dim = false) {
        super._init({reactive: false, can_focus: false});
        this.add_child(new St.Label({text, style_class: dim ? 'maluos-dim' : '', x_expand: true}));
    }
}

class Indicator extends PanelMenu.Button {
    static {
        GObject.registerClass(this);
    }

    _init(ext) {
        super._init(0.5, 'MaluOS');
        this._ext = ext;
        this._state = null;
        this._proxy = null;
        this._signalId = null;
        this._ownerId = null;

        this._icon = new St.Icon({
            gicon: Gio.icon_new_for_string(`${ext.path}/icons/maluos-symbolic.svg`),
            style_class: 'system-status-icon maluos-indicator',
        });
        this.add_child(this._icon);
        this.menu.connect('open-state-changed', (_m, open) => {
            if (open)
                this._rebuild();
        });
        this._rebuild();
        this._connect();
    }

    _connect() {
        // Creating the proxy D-Bus-activates maluos-desktop-session if it is not running.
        this._proxy = new SessionProxy(Gio.DBus.session, BUS_NAME, OBJECT_PATH, (proxy, error) => {
            if (error) {
                console.warn(`maluos-session: no session service: ${error.message}`);
                return;
            }
            if (!this._proxy)
                return;   // destroyed meanwhile
            this._signalId = this._proxy.connectSignal('StateChanged', (_p, _sender, [json]) => this._setState(json));
            this._ownerId = this._proxy.connect('notify::g-name-owner', () => {
                if (!this._proxy.g_name_owner)
                    this._setState(null);
                else
                    this._fetch();
            });
            this._fetch();
        });
    }

    _fetch() {
        this._proxy?.GetStateRemote((result, error) => {
            if (!error && result)
                this._setState(result[0]);
        });
    }

    _setState(json) {
        try {
            this._state = json ? JSON.parse(json) : null;
        } catch (e) {
            console.warn(`maluos-session: bad state: ${e.message}`);
            this._state = null;
        }
        this._updateIcon();
        if (this.menu.isOpen)
            this._rebuild();
    }

    _updateIcon() {
        const s = this._state;
        for (const c of ['maluos-warn', 'maluos-bad', 'maluos-off'])
            this._icon.remove_style_class_name(c);
        if (!s) {
            this._icon.add_style_class_name('maluos-off');
            return;
        }
        const failed = (s.agents || []).some(a => a.active === 'failed');
        const asked = (s.vault?.requests || []).some(r => r.mine_to_decide);
        const down = (s.gateway?.backends || []).some(b => b.enabled && !b.healthy) || asked;
        const over = Object.values(s.me?.budget || {}).some(b => b.spent !== null && b.spent >= b.limit);
        const warn = Object.values(s.me?.budget || {}).some(b => b.spent !== null && b.spent >= b.warn_at * b.limit) || s.updates?.reboot_required || s.office?.revoked || s.office?.presence === 'unreachable';
        if (failed || over)
            this._icon.add_style_class_name('maluos-bad');
        else if (down || warn)
            this._icon.add_style_class_name('maluos-warn');
        else if (!s.gateway?.available)
            this._icon.add_style_class_name('maluos-off');
    }

    _rebuild() {
        const m = this.menu;
        m.removeAll();
        const s = this._state;
        if (!s) {
            m.addMenuItem(new InfoItem('MaluOS'));
            m.addMenuItem(new InfoItem('The session service is not running.', true));
            m.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            const retry = new PopupMenu.PopupMenuItem('Connect');
            retry.connect('activate', () => this._connect());
            m.addMenuItem(retry);
            return;
        }
        const h = s.host || {};
        const header = new InfoItem(`${h.pretty_name || 'MaluOS'} · ${h.hostname || ''}`);
        header.add_style_class_name('maluos-header');
        m.addMenuItem(header);
        if (h.memory)
            m.addMenuItem(new InfoItem(`Memory host: ${h.memory.tenant || 'local'} on this desk`, true));
        else
            m.addMenuItem(new InfoItem('Memory host: not provisioned on this desk', true));
        this._updatesItem(m, s.updates || {});
        this._officeItem(m, s.office || {});

        m.addMenuItem(new PopupMenu.PopupSeparatorMenuItem('Agents'));
        const agents = [...(s.agents || [])].sort((a, b) => Number(b.mine) - Number(a.mine) || a.name.localeCompare(b.name));
        if (agents.length === 0) {
            m.addMenuItem(new InfoItem('No agents on this host', true));
            m.addMenuItem(new InfoItem('sudo maluctl agent create NAME --exec CMD', true));
        }
        for (const a of agents)
            m.addMenuItem(this._agentItem(a));

        // vault grant requests the user must decide (slice 3)
        const asks = (s.vault?.requests || []).filter(r => r.mine_to_decide);
        if (asks.length) {
            m.addMenuItem(new PopupMenu.PopupSeparatorMenuItem(`Requests (${asks.length})`));
            for (const r of asks)
                m.addMenuItem(this._requestItem(r));
        }

        m.addMenuItem(new PopupMenu.PopupSeparatorMenuItem('Models'));
        const g = s.gateway || {};
        if (!g.available) {
            m.addMenuItem(new InfoItem('Gateway: not available on this host', true));
        } else {
            const backends = g.backends || [];
            const healthy = backends.filter(b => b.healthy).length;
            const q = g.queue || {};
            const gw = new PopupMenu.PopupSubMenuMenuItem(`Gateway: ${healthy}/${backends.length} backends · ${q.queued || 0} queued, ${q.running || 0} running`);
            for (const b of backends) {
                const dot = b.healthy ? '●' : '○';
                const item = new InfoItem(`${dot} ${b.name}  ${b.cloud ? 'cloud' : 'local'}${b.loaded?.length ? ' · ' + b.loaded.join(', ') : ''}${b.error ? ' · ' + b.error : ''}`);
                gw.menu.addMenuItem(item);
            }
            if (backends.length === 0)
                gw.menu.addMenuItem(new InfoItem('no backends configured (maluctl gateway backend add)', true));
            m.addMenuItem(gw);
            const me = s.me || {};
            const who = me.principal || `user:${h.user}`;
            m.addMenuItem(new InfoItem(me.enrolled ? `You: ${who}${me.operator ? ' (operator)' : ''}` : `You: ${who} · not enrolled as a principal`, true));
            for (const [period, b] of Object.entries(me.budget || {})) {
                const level = b.spent === null ? '' : b.spent >= b.limit ? '  (exhausted)' : b.spent >= b.warn_at * b.limit ? '  (nearly used)' : '';
                m.addMenuItem(new InfoItem(`Budget this ${period}: ${usd(b.spent)} of ${usd(b.limit)}${level}`, true));
            }
            const recent = me.recent || [];
            if (recent.length) {
                const r = new PopupMenu.PopupSubMenuMenuItem(`Recent calls (${recent.length})`);
                for (const c of recent)
                    r.menu.addMenuItem(new InfoItem(`${hhmm(c.ts)}  ${c.requested || '?'} → ${c.backend || '-'}/${c.model || '-'}  ${c.status || ''}${c.reason ? ' · ' + c.reason : ''}`));
                m.addMenuItem(r);
            }
        }

        const v = s.vault || {};
        if (v.available && v.enrolled) {
            const d = v.delegations || [];
            const vi = new PopupMenu.PopupSubMenuMenuItem(`Vault: ${v.secrets ?? 0} secrets · ${d.length} delegated`);
            for (const c of v.compartments || [])
                vi.menu.addMenuItem(new InfoItem(`compartment ${c}`));
            for (const x of d)
                vi.menu.addMenuItem(new InfoItem(`${x.secret || 'all secrets'} → ${x.to}${x.expires_at ? ' until ' + x.expires_at.slice(0, 10) : ''}`));
            m.addMenuItem(vi);
        } else {
            m.addMenuItem(new InfoItem(v.available ? 'Vault: you are not enrolled' : 'Vault: not available on this host', true));
        }

        const alerts = s.alerts || [];
        if (alerts.length) {
            const al = new PopupMenu.PopupSubMenuMenuItem(`Alerts (${alerts.length})`);
            for (const a of alerts.slice(0, 10))
                al.menu.addMenuItem(new InfoItem(`${a.ts?.slice(11, 16) || ''}  ${a.kind}: ${a.title || ''}`));
            m.addMenuItem(al);
        }

        m.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const desk = new PopupMenu.PopupMenuItem('Open MaluOS Desk');
        desk.connect('activate', () => spawn(['maluos-desk']));
        m.addMenuItem(desk);
        const term = new PopupMenu.PopupMenuItem('Agents in a terminal');
        term.connect('activate', () => spawn(['xdg-terminal-exec', 'sh', '-c', 'maluctl agent list; maluctl gateway status; exec "${SHELL:-bash}"']));
        m.addMenuItem(term);
        const refresh = new PopupMenu.PopupMenuItem('Refresh');
        refresh.connect('activate', () => this._proxy?.RefreshRemote(() => {}));
        m.addMenuItem(refresh);
    }

    // software updates (slice 5): one line, a submenu with the pending list and the actions
    _updatesItem(m, u) {
        if (!u.available)
            return;
        const manual = u.manual_count ?? ((u.pending_count || 0) - (u.automatic_count || 0));
        let text;
        if (u.reboot_required)
            text = 'Updates: restart needed to finish';
        else if (u.pending_error)
            text = 'Updates: unknown (apt busy)';
        else if (!u.pending_count)
            text = `Updates: up to date · lists ${u.lists_refreshed || '?'}`;
        else
            text = `Updates: ${u.pending_count} pending${manual ? ` · ${manual} wait for you` : ''}${u.automatic_count ? ` · ${u.automatic_count} automatic` : ''}`;
        const item = new PopupMenu.PopupSubMenuMenuItem(text);
        if (u.reboot_required)
            item.label.add_style_class_name('maluos-dot-warn');
        const pending = u.pending || [];
        for (const p of pending.slice(0, 12))
            item.menu.addMenuItem(new InfoItem(`${p.name} → ${p.candidate}  ${p.source}${p.security && p.source !== 'security' ? ' (security)' : ''}${p.automatic ? '' : ' · waits for you'}`, true));
        if (pending.length > 12)
            item.menu.addMenuItem(new InfoItem(`… and ${pending.length - 12} more`, true));
        const a = u.automatic || {};
        item.menu.addMenuItem(new InfoItem(`automatic: ${a.enabled ? 'on' : 'off'} · last run ${u.last_automatic_run || 'never'} · lists refreshed ${u.lists_refreshed || '?'}`, true));
        for (const [label, action, when] of [['Install updates…', 'open', !!u.pending_count], ['Restart now', 'restart', !!u.reboot_required], ['Check again', 'refresh', true]]) {
            if (!when)
                continue;
            const it = new PopupMenu.PopupMenuItem(label);
            it.connect('activate', () => this._proxy?.UpdateActionRemote(action, (_r, error) => {
                if (error)
                    Main.notify(`Updates: ${action} failed`, error.message);
            }));
            item.menu.addMenuItem(it);
        }
        m.addMenuItem(item);
    }

    _officeItem(m, o) {
        if (!o.enrolled) {
            m.addMenuItem(new InfoItem('Office: not enrolled (sudo maluctl office enroll URL --code CODE)', true));
            return;
        }
        const name = o.office?.name || o.url;
        const pres = {retired: 'retired by the office', online: 'online', unreachable: 'unreachable', unknown: 'checking in…'}[o.presence] || o.presence;
        const item = new PopupMenu.PopupSubMenuMenuItem(`Office: ${name} · ${pres}`);
        if (o.revoked || o.presence === 'unreachable')
            item.label.add_style_class_name('maluos-dot-warn');
        item.menu.addMenuItem(new InfoItem(`desk ${o.desk?.name || '?'} (#${o.desk?.id ?? '?'}) · ${o.url}`, true));
        item.menu.addMenuItem(new InfoItem(`you: ${o.owner?.display_name || o.owner?.principal || '?'}${o.owner?.email ? ' <' + o.owner.email + '>' : ''}`, true));
        const eps = Object.entries(o.endpoints || {}).filter(([k, v]) => k !== 'models' && v).map(([k]) => k);
        item.menu.addMenuItem(new InfoItem(`published: ${eps.join(', ') || 'nothing'}${o.endpoints?.models ? ' · models ' + o.endpoints.models.join(', ') : ''}${o.gateway ? ' · --model ' + o.gateway : ''}`, true));
        item.menu.addMenuItem(new InfoItem(o.last_heartbeat_at ? `last check-in ${o.last_heartbeat_at}` : 'no check-in yet', true));
        if (o.last_error)
            item.menu.addMenuItem(new InfoItem(o.last_error, true));
        for (const [label, action] of [['Open office…', 'open'], ['Check in now', 'heartbeat']]) {
            const it = new PopupMenu.PopupMenuItem(label);
            it.connect('activate', () => this._proxy?.OfficeActionRemote(action, (_r, error) => {
                if (error)
                    Main.notify(`Office: ${action} failed`, error.message);
            }));
            item.menu.addMenuItem(it);
        }
        m.addMenuItem(item);
    }

    _requestItem(r) {
        const who = r.requester?.includes(':') ? r.requester.split(':')[1] : r.requester;
        const item = new PopupMenu.PopupSubMenuMenuItem(`${r.requester_kind === 'agent' ? 'Agent' : ''} ${who} asks for ${r.secret}`);
        item.label.add_style_class_name('maluos-dot-warn');
        item.menu.addMenuItem(new InfoItem(`${r.level} access${r.purpose ? ' · ' + r.purpose : ''}${r.asked_count > 1 ? ' · asked ' + r.asked_count + ' times' : ''}`, true));
        for (const [label, decision, expires] of [['Allow for a week', 'approve', '7d'], ['Allow for a day', 'approve', '1d'], ['Deny', 'deny', '']]) {
            const it = new PopupMenu.PopupMenuItem(label);
            it.connect('activate', () => this._proxy?.RequestDecideRemote(r.id, decision, expires, (_res, error) => {
                if (error)
                    Main.notify(`Request #${r.id}: ${decision} failed`, error.message);
            }));
            item.menu.addMenuItem(it);
        }
        return item;
    }

    _agentItem(a) {
        const owner = a.mine ? ' · yours' : a.owner ? ` · ${a.owner}` : '';
        const item = new PopupMenu.PopupSubMenuMenuItem(`${DOT[a.active] || '○'} ${a.name}  ${a.active}${a.sub && a.sub !== 'dead' && a.sub !== 'running' ? ' (' + a.sub + ')' : ''}${owner}`);
        item.label.add_style_class_name(DOT_CLASS[a.active] || '');
        item.menu.addMenuItem(new InfoItem(`${a.principal} · ${a.unit}${a.sandbox === 'strict' ? ' · strict sandbox' : ''}${a.mine ? ' · you may start and stop it' : ''}`, true));
        if (a.exec)
            item.menu.addMenuItem(new InfoItem(a.exec, true));
        const actions = a.active === 'active' ? [['Stop', 'stop'], ['Restart', 'restart']] : [['Start', 'start']];
        for (const [label, action] of actions) {
            const it = new PopupMenu.PopupMenuItem(label);
            it.connect('activate', () => this._proxy?.AgentActionRemote(a.name, action, (_r, error) => {
                if (error)
                    Main.notify(`Agent ${a.name}: ${action} failed`, error.message);
            }));
            item.menu.addMenuItem(it);
        }
        const logs = new PopupMenu.PopupMenuItem('Logs');
        logs.connect('activate', () => spawn(['xdg-terminal-exec', 'sh', '-c', `journalctl -f -u ${a.unit} || sudo journalctl -f -u ${a.unit}`]));
        item.menu.addMenuItem(logs);
        return item;
    }

    destroy() {
        if (this._proxy) {
            if (this._signalId !== null)
                this._proxy.disconnectSignal(this._signalId);
            if (this._ownerId !== null)
                this._proxy.disconnect(this._ownerId);
        }
        this._proxy = null;
        super.destroy();
    }
}

export default class MaluOSSessionExtension extends Extension {
    enable() {
        this._indicator = new Indicator(this);
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
