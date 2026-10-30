/* MaluOS: the MaluOS Network tab. See maluos-network.h and README.maluos.md. */
#include <config.h>

#include <adwaita.h>
#include <glib/gi18n.h>
#include <json-glib/json-glib.h>
#include <string.h>

#include "maluos-network.h"
#include "maluos-session.h"

#define jo gsm_maluos_jo
#define ja gsm_maluos_ja
#define js gsm_maluos_js
#define jd gsm_maluos_jd
#define jb gsm_maluos_jb

typedef struct
{
  GtkWidget *row;
  char      *name;
} NamedRow;

struct _GsmMaluosNetworkView
{
  GtkWidget parent_instance;

  GtkWidget *box;
  GtkWidget *banner;
  GtkWidget *page;
  GtkWidget *node_group;
  GtkWidget *note_row;       /* why there is nothing: no gateway, not an operator */
  GtkWidget *node_row;
  GtkWidget *listener_row;
  GtkWidget *share_row;
  GtkWidget *manager_row;
  GtkWidget *lanes_row;
  GtkWidget *keys_row;
  GtkWidget *paired_group;
  GtkWidget *paired_empty_row;
  GtkWidget *office_group;
  GtkWidget *office_row;
  GtkWidget *alerts_row;     /* the estate's open alerts (Phase 13 slice 1) */

  GPtrArray *paired_rows;
  GPtrArray *estate_rows;    /* one row per node of the estate, rebuilt when the set of ids changes */
  GPtrArray *backend_rows;   /* one row per backend the estate's directory gave this gateway (Phase 13 slice 3), in the paired group */

  GsmMaluosSession *session;
  gulong            state_id;
  gboolean          watching;
};

G_DEFINE_FINAL_TYPE (GsmMaluosNetworkView, gsm_maluos_network_view, GTK_TYPE_WIDGET)

/* ---- helpers */

static void
named_row_free (gpointer data)
{
  NamedRow *r = (NamedRow *) data;
  g_free (r->name);
  g_free (r);
}

static GtkWidget *
action_row (const char *title, const char *subtitle)
{
  GtkWidget *row = adw_action_row_new ();
  adw_preferences_row_set_title (ADW_PREFERENCES_ROW (row), title);
  adw_preferences_row_set_use_markup (ADW_PREFERENCES_ROW (row), FALSE);
  if (subtitle)
    adw_action_row_set_subtitle (ADW_ACTION_ROW (row), subtitle);
  return row;
}

static void
set_subtitle (GtkWidget *row, const char *text)
{
  const char *cur = adw_action_row_get_subtitle (ADW_ACTION_ROW (row));
  if (g_strcmp0 (cur, text) != 0)
    adw_action_row_set_subtitle (ADW_ACTION_ROW (row), text ? text : "");
}

static void
set_title (GtkWidget *row, const char *text)
{
  const char *cur = adw_preferences_row_get_title (ADW_PREFERENCES_ROW (row));
  if (g_strcmp0 (cur, text) != 0)
    adw_preferences_row_set_title (ADW_PREFERENCES_ROW (row), text ? text : "");
}

static char *
uptime_text (double s)
{
  if (s >= 86400)
    return g_strdup_printf (_("up %.0f days"), s / 86400);
  if (s >= 3600)
    return g_strdup_printf (_("up %.0f hours"), s / 3600);
  return g_strdup_printf (_("up %.0f minutes"), s / 60);
}

static void
join (GString *s, const char *sep, const char *text)
{
  if (s->len)
    g_string_append (s, sep);
  g_string_append (s, text);
}

/* ---- the paired nodes: one row per remote backend, rebuilt when the set of names changes */

static char *
paired_subtitle (JsonObject *b)
{
  GString *s = g_string_new (NULL);
  const char *endpoint = js (b, "endpoint");
  const char *error = js (b, "error");
  JsonArray *models = ja (b, "models");
  JsonArray *loaded = ja (b, "loaded");

  if (endpoint)
    join (s, " · ", endpoint);
  if (!jb (b, "paired"))
    join (s, " · ", _("no pairing key in the vault"));
  else if (!jb (b, "enabled"))
    join (s, " · ", _("disabled"));
  else if (jb (b, "healthy"))
    join (s, " · ", _("reachable"));
  else
    {
      join (s, " · ", _("unreachable"));
      if (error)
        {
          g_string_append (s, ": ");
          g_string_append (s, error);
        }
    }
  guint nm = models ? json_array_get_length (models) : 0;
  if (nm)
    {
      char *t = g_strdup_printf (ngettext ("%u model", "%u models", nm), nm);
      join (s, " · ", t);
      g_free (t);
      if (loaded && json_array_get_length (loaded))
        {
          g_string_append (s, _(", loaded: "));
          for (guint i = 0; i < json_array_get_length (loaded); i++)
            {
              const char *m = json_array_get_string_element (loaded, i);
              if (i)
                g_string_append (s, ", ");
              g_string_append (s, m ? m : "?");
            }
        }
    }
  return g_string_free (s, FALSE);
}

static void
apply_paired (GsmMaluosNetworkView *self, JsonArray *paired)
{
  guint n = paired ? json_array_get_length (paired) : 0;
  gboolean same = (n == self->paired_rows->len);
  for (guint i = 0; same && i < n; i++)
    same = g_strcmp0 (js (json_array_get_object_element (paired, i), "name"), ((NamedRow *) g_ptr_array_index (self->paired_rows, i))->name) == 0;
  if (!same)
    {
      for (guint i = 0; i < self->paired_rows->len; i++)
        adw_preferences_group_remove (ADW_PREFERENCES_GROUP (self->paired_group), ((NamedRow *) g_ptr_array_index (self->paired_rows, i))->row);
      g_ptr_array_set_size (self->paired_rows, 0);
      for (guint i = 0; i < n; i++)
        {
          JsonObject *b = json_array_get_object_element (paired, i);
          NamedRow *r = g_new0 (NamedRow, 1);
          r->name = g_strdup (js (b, "name") ? js (b, "name") : "?");
          r->row = action_row (r->name, NULL);
          gtk_widget_add_css_class (r->row, "property");
          adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->paired_group), r->row);
          g_ptr_array_add (self->paired_rows, r);
        }
    }
  for (guint i = 0; i < n; i++)
    {
      char *sub = paired_subtitle (json_array_get_object_element (paired, i));
      set_subtitle (((NamedRow *) g_ptr_array_index (self->paired_rows, i))->row, sub);
      g_free (sub);
    }
  gtk_widget_set_visible (self->paired_empty_row, n == 0 && self->backend_rows->len == 0);
}

/* ---- the estate's backends (Phase 13 slice 3): one row per rung the directory gave this gateway, from gateway.estate in the state */

static char *
estate_backend_subtitle (JsonObject *b)
{
  GString *s = g_string_new (NULL);
  const char *endpoint = js (b, "endpoint");
  const char *error = js (b, "error");
  const char *node = js (b, "node");
  const char *ceiling = js (b, "classification_max");
  const char *class_max = js (b, "class_max");
  const char *contribution = js (b, "contribution");
  JsonArray *models = ja (b, "models");
  JsonObject *wait = jo (b, "wait");
  double priority = 0;

  if (node)
    join (s, " · ", node);
  if (endpoint)
    join (s, " · ", endpoint);
  if (!jb (b, "shared"))
    join (s, " · ", _("not shared now"));
  else if (jb (b, "healthy"))
    join (s, " · ", _("reachable"));
  else
    {
      join (s, " · ", _("unreachable"));
      if (error)
        {
          g_string_append (s, ": ");
          g_string_append (s, error);
        }
    }
  guint nm = models ? json_array_get_length (models) : 0;
  if (nm)
    {
      char *t = g_strdup_printf (ngettext ("%u model", "%u models", nm), nm);
      join (s, " · ", t);
      g_free (t);
      g_string_append (s, ": ");
      for (guint i = 0; i < nm && i < 6; i++)
        {
          const char *m = json_array_get_string_element (models, i);
          if (i)
            g_string_append (s, ", ");
          g_string_append (s, m ? m : "?");
        }
      if (nm > 6)
        g_string_append (s, ", …");
    }
  if (wait)
    {
      double w = 0;
      if (jd (wait, "interactive", &w))
        {
          char *t = g_strdup_printf (_("wait %.1f s"), w);
          join (s, " · ", t);
          g_free (t);
        }
    }
  if (ceiling)
    {
      char *t = g_strdup_printf (_("ceiling %s"), ceiling);
      join (s, " · ", t);
      g_free (t);
    }
  if (class_max)
    {
      char *t = g_strdup_printf (_("class ≤ %s"), class_max);
      join (s, " · ", t);
      g_free (t);
    }
  jd (b, "priority", &priority);
  if (priority != 0)
    {
      char *t = g_strdup_printf (_("priority %.0f"), priority);
      join (s, " · ", t);
      g_free (t);
    }
  if (contribution && g_strcmp0 (contribution, "idle") == 0)
    join (s, " · ", _("shares while idle"));
  return g_string_free (s, FALSE);
}

static void
apply_estate_backends (GsmMaluosNetworkView *self, JsonArray *backends)
{
  guint n = backends ? json_array_get_length (backends) : 0;
  gboolean same = (n == self->backend_rows->len);
  for (guint i = 0; same && i < n; i++)
    same = g_strcmp0 (js (json_array_get_object_element (backends, i), "name"), ((NamedRow *) g_ptr_array_index (self->backend_rows, i))->name) == 0;
  if (!same)
    {
      for (guint i = 0; i < self->backend_rows->len; i++)
        adw_preferences_group_remove (ADW_PREFERENCES_GROUP (self->paired_group), ((NamedRow *) g_ptr_array_index (self->backend_rows, i))->row);
      g_ptr_array_set_size (self->backend_rows, 0);
      for (guint i = 0; i < n; i++)
        {
          JsonObject *b = json_array_get_object_element (backends, i);
          NamedRow *r = g_new0 (NamedRow, 1);
          r->name = g_strdup (js (b, "name") ? js (b, "name") : "?");
          r->row = action_row (r->name, NULL);
          gtk_widget_add_css_class (r->row, "property");
          adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->paired_group), r->row);
          g_ptr_array_add (self->backend_rows, r);
        }
    }
  for (guint i = 0; i < n; i++)
    {
      char *sub = estate_backend_subtitle (json_array_get_object_element (backends, i));
      set_subtitle (((NamedRow *) g_ptr_array_index (self->backend_rows, i))->row, sub);
      g_free (sub);
    }
  gtk_widget_set_visible (self->paired_empty_row, n == 0 && self->paired_rows->len == 0);
}

/* ---- the estate (Phase 13 slice 1): one row per node, from office.estate in the session's state */

static char *
estate_node_subtitle (JsonObject *n)
{
  GString *s = g_string_new (NULL);
  const char *kind = js (n, "kind");
  const char *presence = js (n, "presence");
  const char *health = js (n, "health");
  const char *summary = js (n, "summary");
  const char *seen = js (n, "last_seen_at");
  const char *owner = js (n, "owner");

  join (s, " · ", kind ? kind : "node");
  if (owner)
    join (s, " · ", owner);
  join (s, " · ", presence ? presence : "?");
  if (health && g_strcmp0 (health, presence) != 0)
    join (s, " · ", health);
  if (summary && g_strcmp0 (summary, presence) != 0)
    join (s, " · ", summary);
  if (seen)
    {
      char *t = g_strdup_printf (_("seen %s"), seen);
      join (s, " · ", t);
      g_free (t);
    }
  return g_string_free (s, FALSE);
}

static void
apply_estate_nodes (GsmMaluosNetworkView *self, JsonArray *nodes)
{
  guint n = nodes ? json_array_get_length (nodes) : 0;
  gboolean same = (n == self->estate_rows->len);
  for (guint i = 0; same && i < n; i++)
    {
      JsonObject *node = json_array_get_object_element (nodes, i);
      double id = 0;
      jd (node, "id", &id);
      char *key = g_strdup_printf ("%.0f", id);
      same = g_strcmp0 (key, ((NamedRow *) g_ptr_array_index (self->estate_rows, i))->name) == 0;
      g_free (key);
    }
  if (!same)
    {
      for (guint i = 0; i < self->estate_rows->len; i++)
        adw_preferences_group_remove (ADW_PREFERENCES_GROUP (self->office_group), ((NamedRow *) g_ptr_array_index (self->estate_rows, i))->row);
      g_ptr_array_set_size (self->estate_rows, 0);
      for (guint i = 0; i < n; i++)
        {
          JsonObject *node = json_array_get_object_element (nodes, i);
          double id = 0;
          jd (node, "id", &id);
          NamedRow *r = g_new0 (NamedRow, 1);
          r->name = g_strdup_printf ("%.0f", id);
          r->row = action_row (js (node, "name") ? js (node, "name") : "?", NULL);
          gtk_widget_add_css_class (r->row, "property");
          adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->office_group), r->row);
          g_ptr_array_add (self->estate_rows, r);
        }
    }
  for (guint i = 0; i < n; i++)
    {
      JsonObject *node = json_array_get_object_element (nodes, i);
      NamedRow *r = (NamedRow *) g_ptr_array_index (self->estate_rows, i);
      char *sub = estate_node_subtitle (node);
      set_title (r->row, js (node, "name") ? js (node, "name") : "?");
      set_subtitle (r->row, sub);
      g_free (sub);
    }
}

/* ---- the state applied to the widgets */

static void
apply_state (GsmMaluosNetworkView *self, JsonObject *root)
{
  JsonObject *gateway = jo (root, "gateway");
  JsonObject *node = jo (root, "node");
  JsonObject *office = jo (root, "office");
  gboolean gw_ok = gateway && jb (gateway, "available");
  gboolean have = node && jb (node, "available");
  GString *summary = g_string_new (NULL);

  gtk_widget_set_visible (self->note_row, !have);
  gtk_widget_set_visible (self->node_row, have);
  gtk_widget_set_visible (self->listener_row, have);
  gtk_widget_set_visible (self->share_row, have);
  gtk_widget_set_visible (self->manager_row, have);
  gtk_widget_set_visible (self->lanes_row, have);
  gtk_widget_set_visible (self->keys_row, have);

  if (!have)
    {
      if (!gw_ok)
        {
          set_subtitle (self->note_row, _("The inference gateway is not on this computer, so it is not a node of the MaluOS network."));
          g_string_append (summary, "no gateway");
        }
      else if (node && !jb (node, "operator"))
        {
          set_subtitle (self->note_row, _("Only an operator of the gateway sees this node's details. Your own calls are on the Desk's Models page."));
          g_string_append (summary, "not an operator");
        }
      else if (!node)
        {
          set_subtitle (self->note_row, _("The session service is older than this window (maluos-desktop-session 0.8.0 carries the node)."));
          g_string_append (summary, "no node in the state");
        }
      else
        {
          set_subtitle (self->note_row, _("The gateway's node API did not answer (maluos-gateway 0.4.0 or later serves it)."));
          g_string_append (summary, "node API absent");
        }
    }
  else
    {
      const char *name = js (node, "name");
      const char *id = js (node, "id");
      const char *version = js (node, "version");
      JsonObject *machine = jo (node, "machine");
      JsonObject *exposed = jo (node, "exposed");
      JsonObject *share = jo (node, "share");
      JsonObject *lanes = jo (node, "lanes");
      JsonArray *keys = ja (node, "keys");
      JsonArray *paired = ja (node, "paired");
      double up;

      set_title (self->node_row, name ? name : _("This node"));
      {
        GString *s = g_string_new (NULL);
        if (id)
          join (s, " · ", id);
        if (version)
          {
            char *t = g_strdup_printf (_("gateway %s"), version);
            join (s, " · ", t);
            g_free (t);
          }
        if (jd (node, "uptime_s", &up))
          {
            char *t = uptime_text (up);
            join (s, " · ", t);
            g_free (t);
          }
        if (machine && js (machine, "chassis"))
          join (s, " · ", js (machine, "chassis"));
        set_subtitle (self->node_row, s->str);
        g_string_free (s, TRUE);
      }
      {
        double port = 0;
        if (exposed && jb (exposed, "enabled"))
          {
            jd (exposed, "port", &port);
            char *t = g_strdup_printf (_("TCP %s:%.0f, with keys (maluctl gateway key issue). Other MaluOS desks pair with it by hand."),
                                       js (exposed, "host") ? js (exposed, "host") : "?", port);
            set_subtitle (self->listener_row, t);
            g_free (t);
            g_string_append_printf (summary, "node %s, ", name ? name : "?");
          }
        else
          {
            set_subtitle (self->listener_row, _("The Unix socket only: this computer serves itself. sudo maluctl gateway expose opens the network listener."));
            g_string_append_printf (summary, "node %s, ", name ? name : "?");
          }
      }
      {
        GString *s = g_string_new (share && jb (share, "enabled") ? _("Shared with the MaluOS network") : _("Not shared"));
        if (share && js (share, "contribution"))
          {
            g_string_append (s, " · ");
            g_string_append (s, g_strcmp0 (js (share, "contribution"), "idle") == 0 ? _("only while idle") : _("always"));
          }
        if (share && js (share, "chassis"))
          {
            g_string_append (s, " · ");
            g_string_append (s, js (share, "chassis"));
          }
        set_subtitle (self->share_row, s->str);
        g_string_free (s, TRUE);
      }
      {
        const char *seen = js (node, "last_manager_seen_at");
        if (seen)
          {
            char *t = g_strdup_printf (_("Last call with a node key at %s"), seen);
            set_subtitle (self->manager_row, t);
            g_free (t);
          }
        else
          set_subtitle (self->manager_row, _("No manager has called this node yet (the Sovereign LLM Manager registers it with a node key)."));
      }
      {
        GString *s = g_string_new (NULL);
        guint nl = 0;
        GList *names = lanes ? json_object_get_members (lanes) : NULL;
        for (GList *l = names; l; l = l->next)
          {
            JsonObject *lane = jo (lanes, (const char *) l->data);
            double cap = 0, running = 0, queued = 0;
            jd (lane, "capacity", &cap);
            jd (lane, "running", &running);
            jd (lane, "queued", &queued);
            char *t = g_strdup_printf ("%s (%s): %.0f of %.0f running, %.0f queued%s", (const char *) l->data,
                                       js (lane, "kind") ? js (lane, "kind") : "?", running, cap, queued,
                                       jb (lane, "paused") ? _(", paused") : "");
            join (s, "; ", t);
            g_free (t);
            nl++;
          }
        g_list_free (names);
        set_subtitle (self->lanes_row, s->len ? s->str : _("No lane: no backend is configured."));
        g_string_free (s, TRUE);
        g_string_append_printf (summary, "%u lanes, ", nl);
      }
      {
        guint nk = keys ? json_array_get_length (keys) : 0, inference = 0, nodes = 0, revoked = 0;
        for (guint i = 0; i < nk; i++)
          {
            JsonObject *k = json_array_get_object_element (keys, i);
            if (js (k, "revoked_at"))
              revoked++;
            else if (g_strcmp0 (js (k, "kind"), "node") == 0)
              nodes++;
            else
              inference++;
          }
        char *t = g_strdup_printf (_("%u inference, %u node, %u revoked. A key names a principal; its calls are in the ledger under it."),
                                   inference, nodes, revoked);
        set_subtitle (self->keys_row, nk ? t : _("None issued. sudo maluctl gateway key issue --name NAME mints one for a desk, a tool or the manager."));
        g_free (t);
        g_string_append_printf (summary, "%u paired, %u keys, %s", paired ? json_array_get_length (paired) : 0, nk,
                                exposed && jb (exposed, "enabled") ? "exposed" : "socket only");
      }
      apply_paired (self, paired);
    }
  if (!have)
    apply_paired (self, NULL);

  /* the office and its estate (Phase 13 slice 1): the nodes the office publishes to this desk's owner */
  {
    JsonObject *estate = office ? jo (office, "estate") : NULL;
    gboolean have_estate = estate && jb (estate, "available");
    JsonObject *o = office ? jo (office, "office") : NULL;
    const char *name = o ? js (o, "name") : NULL;

    if (office && jb (office, "enrolled") && have_estate)
      {
        JsonObject *counts = jo (estate, "counts");
        JsonArray *nodes = ja (estate, "nodes");
        JsonArray *alerts = ja (estate, "alerts");
        double nn = 0, online = 0, nalerts = 0;
        if (counts)
          {
            jd (counts, "nodes", &nn);
            jd (counts, "online", &online);
            jd (counts, "alerts", &nalerts);
          }
        char *title = g_strdup_printf (_("Estate of %s"), name ? name : "the office");
        set_title (self->office_row, title);
        g_free (title);
        char *t = g_strdup_printf (_("%.0f nodes, %.0f online, %.0f open alerts%s. Read-only: operator actions on a node come with the delegation envelope (slice 2)."),
                                   nn, online, nalerts, jb (estate, "stale") ? _(" (cached: the office did not answer)") : "");
        set_subtitle (self->office_row, t);
        g_free (t);
        {
          GString *a = g_string_new (NULL);
          guint na = alerts ? json_array_get_length (alerts) : 0, open = 0;
          for (guint i = 0; i < na; i++)
            {
              JsonObject *al = json_array_get_object_element (alerts, i);
              if (js (al, "cleared_at"))
                continue;
              open++;
              char *line = g_strdup_printf ("%s: %s (%s)", js (al, "node") ? js (al, "node") : "?", js (al, "title") ? js (al, "title") : "?",
                                            js (al, "severity") ? js (al, "severity") : "?");
              join (a, "; ", line);
              g_free (line);
            }
          set_subtitle (self->alerts_row, open ? a->str : _("No open alert. A unit down, a failed agent, a vault alert, a required restart or a full disk raises one; it clears with the next report."));
          g_string_free (a, TRUE);
        }
        gtk_widget_set_visible (self->alerts_row, TRUE);
        apply_estate_nodes (self, nodes);
        g_string_append_printf (summary, ", estate %.0f nodes (%.0f online, %.0f alert%s)", nn, online, nalerts, nalerts == 1 ? "" : "s");
      }
    else
      {
        if (office && jb (office, "enrolled"))
          {
            const char *presence = js (office, "presence");
            const char *why = estate ? js (estate, "error") : NULL;
            set_title (self->office_row, name ? name : _("Office"));
            char *t = g_strdup_printf (_("This desk is %s. The estate appears here when the office publishes it to you (system managers see every node, its health and its alerts).%s%s"),
                                       presence ? presence : "enrolled", why ? " " : "", why ? why : "");
            set_subtitle (self->office_row, t);
            g_free (t);
          }
        else
          {
            set_title (self->office_row, _("No office"));
            set_subtitle (self->office_row, _("Not enrolled in an office. Pairing by hand works without one; the estate's directory needs it."));
          }
        gtk_widget_set_visible (self->alerts_row, FALSE);
        apply_estate_nodes (self, NULL);
      }
  }

  /* the estate's backends (Phase 13 slice 3): the rungs the directory gave this gateway, for everyone who sees the gateway */
  {
    JsonObject *est = gateway ? jo (gateway, "estate") : NULL;
    JsonArray *backends = est ? ja (est, "backends") : NULL;
    guint nb = backends ? json_array_get_length (backends) : 0;
    apply_estate_backends (self, backends);
    if (nb)
      {
        JsonArray *eds = ja (est, "editions");
        g_string_append_printf (summary, ", %u estate backend%s", nb, nb == 1 ? "" : "s");
        if (eds && json_array_get_length (eds))
          g_string_append (summary, " (scheduler)");
      }
  }

  gsm_maluos_session_set_summary (self->session, "network", summary->str);
  g_string_free (summary, TRUE);
}

static void
on_state (GsmMaluosSession *, JsonObject *state, gpointer data)
{
  apply_state ((GsmMaluosNetworkView *) data, state);
}

void
maluos_network_freeze (GsmMaluosNetworkView *self)
{
  if (!self->watching)
    return;
  self->watching = FALSE;
  gsm_maluos_session_unwatch (self->session, GSM_MALUOS_WATCH_STATE);
}

void
maluos_network_thaw (GsmMaluosNetworkView *self)
{
  if (self->watching)
    return;
  self->watching = TRUE;
  gsm_maluos_session_watch (self->session, GSM_MALUOS_WATCH_STATE);
}

/* ---- GObject */

static void
gsm_maluos_network_view_dispose (GObject *object)
{
  GsmMaluosNetworkView *self = GSM_MALUOS_NETWORK_VIEW (object);

  maluos_network_freeze (self);
  if (self->state_id)
    {
      g_signal_handler_disconnect (self->session, self->state_id);
      self->state_id = 0;
    }
  if (self->paired_rows)
    {
      g_ptr_array_free (self->paired_rows, TRUE);
      self->paired_rows = NULL;
    }
  if (self->estate_rows)
    {
      g_ptr_array_free (self->estate_rows, TRUE);
      self->estate_rows = NULL;
    }
  if (self->backend_rows)
    {
      g_ptr_array_free (self->backend_rows, TRUE);
      self->backend_rows = NULL;
    }
  g_clear_pointer (&self->box, gtk_widget_unparent);

  G_OBJECT_CLASS (gsm_maluos_network_view_parent_class)->dispose (object);
}

static void
gsm_maluos_network_view_class_init (GsmMaluosNetworkViewClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (klass);

  object_class->dispose = gsm_maluos_network_view_dispose;
  gtk_widget_class_set_layout_manager_type (widget_class, GTK_TYPE_BIN_LAYOUT);
}

static void
gsm_maluos_network_view_init (GsmMaluosNetworkView *self)
{
  self->paired_rows = g_ptr_array_new_with_free_func (named_row_free);
  self->estate_rows = g_ptr_array_new_with_free_func (named_row_free);
  self->backend_rows = g_ptr_array_new_with_free_func (named_row_free);
  self->session = gsm_maluos_session_get ();

  self->box = gtk_box_new (GTK_ORIENTATION_VERTICAL, 0);
  gtk_widget_set_parent (self->box, GTK_WIDGET (self));

  self->banner = adw_banner_new (_("The MaluOS session service is not answering"));
  g_object_bind_property (self->session, "stale", self->banner, "revealed", G_BINDING_SYNC_CREATE);
  gtk_box_append (GTK_BOX (self->box), self->banner);

  self->page = adw_preferences_page_new ();
  gtk_widget_set_vexpand (self->page, TRUE);
  gtk_box_append (GTK_BOX (self->box), self->page);

  self->node_group = adw_preferences_group_new ();
  adw_preferences_group_set_title (ADW_PREFERENCES_GROUP (self->node_group), _("This Node"));
  adw_preferences_group_set_description (ADW_PREFERENCES_GROUP (self->node_group),
                                         _("As the gateway's node API reports it (maluctl gateway node status)."));
  adw_preferences_page_add (ADW_PREFERENCES_PAGE (self->page), ADW_PREFERENCES_GROUP (self->node_group));
  self->note_row = action_row (_("Not a node"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->node_group), self->note_row);
  self->node_row = action_row (_("This node"), "—");
  gtk_widget_add_css_class (self->node_row, "property");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->node_group), self->node_row);
  self->listener_row = action_row (_("Listener"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->node_group), self->listener_row);
  self->share_row = action_row (_("Sharing"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->node_group), self->share_row);
  self->manager_row = action_row (_("Manager"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->node_group), self->manager_row);
  self->lanes_row = action_row (_("Lanes"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->node_group), self->lanes_row);
  self->keys_row = action_row (_("Keys issued"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->node_group), self->keys_row);

  self->paired_group = adw_preferences_group_new ();
  adw_preferences_group_set_title (ADW_PREFERENCES_GROUP (self->paired_group), _("Paired Nodes"));
  adw_preferences_group_set_description (ADW_PREFERENCES_GROUP (self->paired_group),
                                         _("Shared MaluOS GPU hosts this computer reaches: the estate's directory gives it one rung per host it may use (estate:NAME, over the overlay with its own inference key), and a host paired by hand is a remote backend."));
  adw_preferences_page_add (ADW_PREFERENCES_PAGE (self->page), ADW_PREFERENCES_GROUP (self->paired_group));
  self->paired_empty_row = action_row (_("No node paired"),
                                       _("sudo maluctl gateway backend add NAME URL --key KEY pairs a shared GPU host; its models are then --model NAME/…"));
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->paired_group), self->paired_empty_row);

  self->office_group = adw_preferences_group_new ();
  adw_preferences_group_set_title (ADW_PREFERENCES_GROUP (self->office_group), _("Estate"));
  adw_preferences_page_add (ADW_PREFERENCES_PAGE (self->page), ADW_PREFERENCES_GROUP (self->office_group));
  adw_preferences_group_set_description (ADW_PREFERENCES_GROUP (self->office_group),
                                         _("The nodes of the office's estate, their health and alerts, as the office publishes them to you (maluctl office estate)."));
  self->office_row = action_row (_("No office"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->office_group), self->office_row);
  self->alerts_row = action_row (_("Open alerts"), "—");
  gtk_widget_set_visible (self->alerts_row, FALSE);
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->office_group), self->alerts_row);

  self->state_id = g_signal_connect (self->session, "state", G_CALLBACK (on_state), self);
  if (gsm_maluos_session_get_state (self->session))
    apply_state (self, gsm_maluos_session_get_state (self->session));
}

GsmMaluosNetworkView *
gsm_maluos_network_view_new (void)
{
  return GSM_MALUOS_NETWORK_VIEW (g_object_new (GSM_TYPE_MALUOS_NETWORK_VIEW, NULL));
}
