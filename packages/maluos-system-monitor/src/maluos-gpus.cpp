/* MaluOS: the GPUs tab. See maluos-gpus.h and README.maluos.md. */
#include <config.h>

#include <adwaita.h>
#include <glib/gi18n.h>
#include <json-glib/json-glib.h>
#include <string.h>

#include "maluos-gpus.h"
#include "maluos-session.h"

#define jo gsm_maluos_jo
#define ja gsm_maluos_ja
#define js gsm_maluos_js
#define jd gsm_maluos_jd
#define jb gsm_maluos_jb

typedef struct
{
  GtkWidget *row;      /* AdwActionRow */
  GtkWidget *level;    /* GtkLevelBar: busy */
  GtkWidget *pct;      /* GtkLabel */
  char      *key;
} GpuRow;

struct _GsmMaluosGpusView
{
  GtkWidget parent_instance;

  GtkWidget *box;
  GtkWidget *banner;
  GtkWidget *page;
  GtkWidget *local_group;
  GtkWidget *empty_row;
  GtkWidget *share_row;
  GtkWidget *rule_row;
  GtkWidget *models_row;
  GtkWidget *queue_row;
  GtkWidget *office_row;

  GPtrArray *rows;

  GsmMaluosSession *session;   /* the process's one client, not owned */
  gulong            state_id;
  gboolean          watching;
  gboolean          updating_switch;
};

G_DEFINE_FINAL_TYPE (GsmMaluosGpusView, gsm_maluos_gpus_view, GTK_TYPE_WIDGET)

/* ---- rows */

static void
gpu_row_free (gpointer data)
{
  GpuRow *r = (GpuRow *) data;
  g_free (r->key);
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

static char *
gpu_key (JsonObject *g)
{
  return g_strdup_printf ("%s|%s|%s", js (g, "vendor") ? js (g, "vendor") : "", js (g, "model") ? js (g, "model") : "",
                          js (g, "pci") ? js (g, "pci") : "");
}

static char *
gpu_subtitle (JsonObject *g)
{
  GString *s = g_string_new (NULL);
  double v, u, t, p, l;
  const char *driver = js (g, "driver");
  const char *compute = js (g, "compute");

  if (driver)
    g_string_append_printf (s, _("driver %s"), driver);
  if (jd (g, "vram_mb", &v) && v > 0)
    {
      if (s->len)
        g_string_append (s, " · ");
      if (jd (g, "vram_used_mb", &u))
        g_string_append_printf (s, _("%.1f of %.1f GB"), u / 1024.0, v / 1024.0);
      else
        g_string_append_printf (s, _("%.1f GB"), v / 1024.0);
    }
  if (jd (g, "temp_c", &t))
    {
      if (s->len)
        g_string_append (s, " · ");
      g_string_append_printf (s, _("%.0f °C"), t);
    }
  if (jd (g, "power_w", &p))
    {
      if (s->len)
        g_string_append (s, " · ");
      if (jd (g, "power_limit_w", &l) && l > 0)
        g_string_append_printf (s, _("%.0f of %.0f W"), p, l);
      else
        g_string_append_printf (s, _("%.0f W"), p);
    }
  if (compute)
    {
      if (s->len)
        g_string_append (s, " · ");
      g_string_append_printf (s, _("compute %s"), compute);
    }
  if (!s->len)
    g_string_append (s, _("no driver numbers (the driver gives none, or nvidia-smi is not installed)"));
  return g_string_free (s, FALSE);
}

static GpuRow *
gpu_row_new (GsmMaluosGpusView *self, JsonObject *g)
{
  GpuRow *r = g_new0 (GpuRow, 1);
  const char *model = js (g, "model");

  r->key = gpu_key (g);
  r->row = action_row (model ? model : _("GPU"), NULL);
  gtk_widget_add_css_class (r->row, "property");

  GtkWidget *suffix = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 8);
  gtk_widget_set_valign (suffix, GTK_ALIGN_CENTER);
  r->level = gtk_level_bar_new_for_interval (0, 100);
  gtk_widget_set_size_request (r->level, 120, -1);
  gtk_widget_set_valign (r->level, GTK_ALIGN_CENTER);
  r->pct = gtk_label_new ("—");
  gtk_label_set_width_chars (GTK_LABEL (r->pct), 5);
  gtk_label_set_xalign (GTK_LABEL (r->pct), 1.0);
  gtk_widget_add_css_class (r->pct, "numeric");
  gtk_box_append (GTK_BOX (suffix), r->level);
  gtk_box_append (GTK_BOX (suffix), r->pct);
  adw_action_row_add_suffix (ADW_ACTION_ROW (r->row), suffix);

  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->local_group), r->row);
  return r;
}

static void
gpu_row_update (GpuRow *r, JsonObject *g)
{
  double busy;
  char *sub = gpu_subtitle (g);
  set_subtitle (r->row, sub);
  g_free (sub);
  if (jd (g, "busy_pct", &busy))
    {
      char *txt = g_strdup_printf ("%.0f %%", busy);
      gtk_level_bar_set_value (GTK_LEVEL_BAR (r->level), CLAMP (busy, 0, 100));
      gtk_label_set_text (GTK_LABEL (r->pct), txt);
      g_free (txt);
      gtk_widget_set_visible (r->level, TRUE);
    }
  else
    {
      gtk_level_bar_set_value (GTK_LEVEL_BAR (r->level), 0);
      gtk_label_set_text (GTK_LABEL (r->pct), "—");
      gtk_widget_set_visible (r->level, FALSE);
    }
}

static void
clear_rows (GsmMaluosGpusView *self)
{
  for (guint i = 0; i < self->rows->len; i++)
    {
      GpuRow *r = (GpuRow *) g_ptr_array_index (self->rows, i);
      adw_preferences_group_remove (ADW_PREFERENCES_GROUP (self->local_group), r->row);
    }
  g_ptr_array_set_size (self->rows, 0);
}

static const char *
rule_text (const char *rule)
{
  if (g_strcmp0 (rule, "always") == 0)
    return _("A server shares its GPU with the MaluOS network always.");
  if (g_strcmp0 (rule, "opt-in-idle") == 0)
    return _("A laptop shares its GPU when its owner opts in, and only while it is idle.");
  return _("A dedicated desktop shares its GPU when its owner opts in.");
}

/* ---- the state applied to the widgets */

static void
apply_state (GsmMaluosGpusView *self, JsonObject *root)
{
  JsonObject *host = jo (root, "host");
  JsonObject *gateway = jo (root, "gateway");
  JsonObject *share = jo (gateway, "share");
  JsonObject *office = jo (root, "office");
  JsonArray *gpus = ja (host, "gpus");
  const char *chassis = js (host, "chassis");
  const char *rule = js (host, "contribution_rule");
  guint n = gpus ? json_array_get_length (gpus) : 0;

  /* this computer's GPUs: rebuild when the set changed, update in place otherwise */
  gboolean same = (n == self->rows->len);
  for (guint i = 0; same && i < n; i++)
    {
      char *k = gpu_key (json_array_get_object_element (gpus, i));
      same = g_strcmp0 (k, ((GpuRow *) g_ptr_array_index (self->rows, i))->key) == 0;
      g_free (k);
    }
  if (!same)
    {
      clear_rows (self);
      for (guint i = 0; i < n; i++)
        g_ptr_array_add (self->rows, gpu_row_new (self, json_array_get_object_element (gpus, i)));
    }
  for (guint i = 0; i < n; i++)
    gpu_row_update ((GpuRow *) g_ptr_array_index (self->rows, i), json_array_get_object_element (gpus, i));

  gtk_widget_set_visible (self->empty_row, n == 0);
  if (n == 0)
    {
      if (g_strcmp0 (chassis, "vm") == 0 || g_strcmp0 (chassis, "container") == 0)
        set_subtitle (self->empty_row, _("A virtual machine: give it a GPU by passthrough, or use a GPU elsewhere on the MaluOS network."));
      else if (host && !jb (host, "nvidia_smi"))
        set_subtitle (self->empty_row, _("For an RTX card install the nvidia component: sudo apt install maluos-nvidia"));
      else
        set_subtitle (self->empty_row, _("No GPU was found on this computer."));
    }

  /* sharing */
  gboolean gw_ok = gateway && jb (gateway, "available");
  self->updating_switch = TRUE;
  adw_switch_row_set_active (ADW_SWITCH_ROW (self->share_row), share && jb (share, "enabled"));
  self->updating_switch = FALSE;
  gtk_widget_set_sensitive (self->share_row, gw_ok && n > 0);
  {
    GString *s = g_string_new (rule_text (rule));
    if (!gw_ok)
      g_string_append_printf (s, " %s", _("The inference gateway is not on this computer."));
    else if (share && !jb (share, "configured"))
      g_string_append_printf (s, " %s", _("Not set by hand: the chassis rule applies."));
    if (share && jb (share, "exposed"))
      g_string_append_printf (s, " %s", _("Exposed on the network."));
    set_subtitle (self->share_row, s->str);
    g_string_free (s, TRUE);
  }
  {
    const char *c = share ? js (share, "contribution") : NULL;
    char *txt = g_strdup_printf ("%s%s%s",
                                 g_strcmp0 (c, "idle") == 0 ? _("Only while idle") : _("Always"),
                                 chassis ? " · " : "", chassis ? chassis : "");
    set_subtitle (self->rule_row, txt);
    g_free (txt);
  }

  /* models and the queue, from the gateway's local backends */
  {
    GString *models = g_string_new (NULL);
    JsonArray *backends = ja (gateway, "backends");
    for (guint i = 0; backends && i < json_array_get_length (backends); i++)
      {
        JsonObject *b = json_array_get_object_element (backends, i);
        JsonArray *loaded = ja (b, "loaded");
        if (jb (b, "cloud") || !loaded)
          continue;
        for (guint k = 0; k < json_array_get_length (loaded); k++)
          {
            const char *m = json_array_get_string_element (loaded, k);
            if (!m)
              continue;
            if (models->len)
              g_string_append (models, ", ");
            g_string_append (models, m);
          }
      }
    set_subtitle (self->models_row, models->len ? models->str : (gw_ok ? _("None loaded") : _("No gateway")));
    g_string_free (models, TRUE);

    JsonObject *queue = jo (gateway, "queue");
    double queued = 0, running = 0;
    if (queue)
      {
        jd (queue, "queued", &queued);
        jd (queue, "running", &running);
      }
    char *q = g_strdup_printf (_("%.0f queued, %.0f running"), queued, running);
    set_subtitle (self->queue_row, gw_ok ? q : _("No gateway"));
    g_free (q);
  }

  /* the office */
  if (office && jb (office, "enrolled"))
    {
      JsonObject *o = jo (office, "office");
      const char *name = o ? js (o, "name") : NULL;
      char *txt = g_strdup_printf (_("Enrolled in %s. The network's GPUs appear here with the estate's node directory (Phase 13 slice 1)."),
                                   name ? name : _("an office"));
      set_subtitle (self->office_row, txt);
      g_free (txt);
    }
  else
    set_subtitle (self->office_row, _("Not enrolled in an office. Enrol this desk (maluctl office enroll) to see the network's GPUs."));

  char *summary = g_strdup_printf ("session reachable, %u gpus, chassis %s, rule %s, share %s, gateway %s",
                                   n, chassis ? chassis : "?", rule ? rule : "?",
                                   share ? (jb (share, "enabled") ? "on" : "off") : "?", gw_ok ? "ok" : "absent");
  gsm_maluos_session_set_summary (self->session, "gpus", summary);
  g_free (summary);
}

static void
on_state (GsmMaluosSession *, JsonObject *state, gpointer data)
{
  apply_state ((GsmMaluosGpusView *) data, state);
}

void
maluos_gpus_freeze (GsmMaluosGpusView *self)
{
  if (!self->watching)
    return;
  self->watching = FALSE;
  gsm_maluos_session_unwatch (self->session, GSM_MALUOS_WATCH_STATE);
}

void
maluos_gpus_thaw (GsmMaluosGpusView *self)
{
  if (self->watching)
    return;
  self->watching = TRUE;
  gsm_maluos_session_watch (self->session, GSM_MALUOS_WATCH_STATE);
}

/* ---- the one action: the sharing switch runs maluctl through polkit */

static void
on_share_done (gboolean ok, const char *output, gpointer data)
{
  GsmMaluosGpusView *self = (GsmMaluosGpusView *) data;
  if (!ok)
    g_warning ("maluos gpus: maluctl gateway share: %s", output);
  gtk_widget_set_sensitive (self->share_row, TRUE);
  gsm_maluos_session_update (self->session);
  g_object_unref (self);
}

static void
on_share_toggled (GObject *, GParamSpec *, gpointer data)
{
  GsmMaluosGpusView *self = (GsmMaluosGpusView *) data;

  if (self->updating_switch)
    return;
  gboolean on = adw_switch_row_get_active (ADW_SWITCH_ROW (self->share_row));
  const char *argv[] = { "pkexec", "maluctl", "gateway", "share", on ? "on" : "off", NULL };
  gtk_widget_set_sensitive (self->share_row, FALSE);
  gsm_maluos_run (argv, on_share_done, g_object_ref (self));
}

/* ---- GObject */

static void
gsm_maluos_gpus_view_dispose (GObject *object)
{
  GsmMaluosGpusView *self = GSM_MALUOS_GPUS_VIEW (object);

  maluos_gpus_freeze (self);
  if (self->state_id)
    {
      g_signal_handler_disconnect (self->session, self->state_id);
      self->state_id = 0;
    }
  if (self->rows)
    {
      g_ptr_array_free (self->rows, TRUE);
      self->rows = NULL;
    }
  g_clear_pointer (&self->box, gtk_widget_unparent);

  G_OBJECT_CLASS (gsm_maluos_gpus_view_parent_class)->dispose (object);
}

static void
gsm_maluos_gpus_view_class_init (GsmMaluosGpusViewClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (klass);

  object_class->dispose = gsm_maluos_gpus_view_dispose;
  gtk_widget_class_set_layout_manager_type (widget_class, GTK_TYPE_BIN_LAYOUT);
}

static void
gsm_maluos_gpus_view_init (GsmMaluosGpusView *self)
{
  self->rows = g_ptr_array_new_with_free_func (gpu_row_free);
  self->session = gsm_maluos_session_get ();

  self->box = gtk_box_new (GTK_ORIENTATION_VERTICAL, 0);
  gtk_widget_set_parent (self->box, GTK_WIDGET (self));

  self->banner = adw_banner_new (_("The MaluOS session service is not answering"));
  g_object_bind_property (self->session, "stale", self->banner, "revealed", G_BINDING_SYNC_CREATE);
  gtk_box_append (GTK_BOX (self->box), self->banner);

  self->page = adw_preferences_page_new ();
  gtk_widget_set_vexpand (self->page, TRUE);
  gtk_box_append (GTK_BOX (self->box), self->page);

  self->local_group = adw_preferences_group_new ();
  adw_preferences_group_set_title (ADW_PREFERENCES_GROUP (self->local_group), _("This Computer"));
  adw_preferences_group_set_description (ADW_PREFERENCES_GROUP (self->local_group),
                                         _("Read by maluctl gpu status: the driver's numbers, every two seconds."));
  adw_preferences_page_add (ADW_PREFERENCES_PAGE (self->page), ADW_PREFERENCES_GROUP (self->local_group));
  self->empty_row = action_row (_("No GPU on this computer"), NULL);
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->local_group), self->empty_row);

  GtkWidget *share_group = adw_preferences_group_new ();
  adw_preferences_group_set_title (ADW_PREFERENCES_GROUP (share_group), _("Sharing"));
  adw_preferences_page_add (ADW_PREFERENCES_PAGE (self->page), ADW_PREFERENCES_GROUP (share_group));
  self->share_row = adw_switch_row_new ();
  adw_preferences_row_set_title (ADW_PREFERENCES_ROW (self->share_row), _("Share with the MaluOS network"));
  adw_preferences_row_set_use_markup (ADW_PREFERENCES_ROW (self->share_row), FALSE);
  gtk_widget_set_sensitive (self->share_row, FALSE);
  g_signal_connect (self->share_row, "notify::active", G_CALLBACK (on_share_toggled), self);
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (share_group), self->share_row);
  self->rule_row = action_row (_("Contribution"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (share_group), self->rule_row);
  self->models_row = action_row (_("Models loaded"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (share_group), self->models_row);
  self->queue_row = action_row (_("Queue on this computer"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (share_group), self->queue_row);

  GtkWidget *estate_group = adw_preferences_group_new ();
  adw_preferences_group_set_title (ADW_PREFERENCES_GROUP (estate_group), _("MaluOS Network"));
  adw_preferences_page_add (ADW_PREFERENCES_PAGE (self->page), ADW_PREFERENCES_GROUP (estate_group));
  self->office_row = action_row (_("Other GPUs"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (estate_group), self->office_row);

  self->state_id = g_signal_connect (self->session, "state", G_CALLBACK (on_state), self);
  if (gsm_maluos_session_get_state (self->session))
    apply_state (self, gsm_maluos_session_get_state (self->session));
}

GsmMaluosGpusView *
gsm_maluos_gpus_view_new (void)
{
  return GSM_MALUOS_GPUS_VIEW (g_object_new (GSM_TYPE_MALUOS_GPUS_VIEW, NULL));
}
