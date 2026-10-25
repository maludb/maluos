/* MaluOS: the GPUs tab. See maluos-gpus.h and README.maluos.md. */
#include <config.h>

#include <adwaita.h>
#include <gio/gio.h>
#include <glib/gi18n.h>
#include <json-glib/json-glib.h>
#include <stdlib.h>
#include <string.h>

#include "maluos-gpus.h"

#define SESSION_NAME  "com.maluos.Session"
#define SESSION_PATH  "/com/maluos/Session"
#define SESSION_IFACE "com.maluos.Session1"

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

  GDBusProxy   *proxy;
  GCancellable *cancellable;
  guint         timeout;
  guint         interval_ms;
  gboolean      in_flight;
  gboolean      available;
  gboolean      answered_once;
  gboolean      updating_switch;
  gboolean      self_test;
  guint         self_test_timeout;
  gint64        self_test_deadline;   /* monotonic µs */
  char         *summary;
  char         *last_error;
};

G_DEFINE_FINAL_TYPE (GsmMaluosGpusView, gsm_maluos_gpus_view, GTK_TYPE_WIDGET)

enum {
  PROP_0,
  PROP_AVAILABLE,
  N_PROPS
};

static GParamSpec *properties[N_PROPS];

/* ---- JSON helpers: every missing or null member reads as "not there" */

static JsonObject *
jo (JsonObject *o, const char *name)
{
  if (!o || !json_object_has_member (o, name))
    return NULL;
  JsonNode *n = json_object_get_member (o, name);
  return JSON_NODE_HOLDS_OBJECT (n) ? json_node_get_object (n) : NULL;
}

static JsonArray *
ja (JsonObject *o, const char *name)
{
  if (!o || !json_object_has_member (o, name))
    return NULL;
  JsonNode *n = json_object_get_member (o, name);
  return JSON_NODE_HOLDS_ARRAY (n) ? json_node_get_array (n) : NULL;
}

static const char *
js (JsonObject *o, const char *name)
{
  if (!o || !json_object_has_member (o, name))
    return NULL;
  JsonNode *n = json_object_get_member (o, name);
  if (!JSON_NODE_HOLDS_VALUE (n) || json_node_get_value_type (n) != G_TYPE_STRING)
    return NULL;
  return json_node_get_string (n);
}

static gboolean
jd (JsonObject *o, const char *name, double *out)
{
  if (!o || !json_object_has_member (o, name))
    return FALSE;
  JsonNode *n = json_object_get_member (o, name);
  if (!JSON_NODE_HOLDS_VALUE (n))
    return FALSE;
  GType t = json_node_get_value_type (n);
  if (t == G_TYPE_INT64)
    *out = (double) json_node_get_int (n);
  else if (t == G_TYPE_DOUBLE)
    *out = json_node_get_double (n);
  else
    return FALSE;
  return TRUE;
}

static gboolean
jb (JsonObject *o, const char *name)
{
  if (!o || !json_object_has_member (o, name))
    return FALSE;
  JsonNode *n = json_object_get_member (o, name);
  return JSON_NODE_HOLDS_VALUE (n) && json_node_get_value_type (n) == G_TYPE_BOOLEAN && json_node_get_boolean (n);
}

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
      const char *name = js (office, "name");
      char *txt = g_strdup_printf (_("Enrolled in %s. The network's GPUs appear here with the estate's node directory (Phase 13 slice 1)."),
                                   name ? name : _("an office"));
      set_subtitle (self->office_row, txt);
      g_free (txt);
    }
  else
    set_subtitle (self->office_row, _("Not enrolled in an office. Enrol this desk (maluctl office enroll) to see the network's GPUs."));

  g_free (self->summary);
  self->summary = g_strdup_printf ("%u gpus, chassis %s, rule %s, share %s, gateway %s",
                                   n, chassis ? chassis : "?", rule ? rule : "?",
                                   share ? (jb (share, "enabled") ? "on" : "off") : "?", gw_ok ? "ok" : "absent");
}

/* ---- the session service */

static void
set_available (GsmMaluosGpusView *self, gboolean available)
{
  if (self->available == available)
    return;
  self->available = available;
  g_object_notify_by_pspec (G_OBJECT (self), properties[PROP_AVAILABLE]);
}

static void
self_test_done (GsmMaluosGpusView *self, gboolean ok)
{
  if (!self->self_test)
    return;
  self->self_test = FALSE;
  if (self->self_test_timeout)
    {
      g_source_remove (self->self_test_timeout);
      self->self_test_timeout = 0;
    }
  if (ok)
    g_print ("self-test ok: GPUs: session reachable, %s\n", self->summary ? self->summary : "no summary");
  else
    g_print ("self-test FAIL: GPUs: the MaluOS session service did not answer%s%s\n",
             self->last_error ? ": " : "", self->last_error ? self->last_error : "");
  fflush (stdout);
  exit (ok ? 0 : 1);
}

static void
on_state (GObject *source, GAsyncResult *res, gpointer data)
{
  GsmMaluosGpusView *self = (GsmMaluosGpusView *) data;
  GError *error = NULL;
  GVariant *ret = g_dbus_proxy_call_finish (G_DBUS_PROXY (source), res, &error);

  if (g_error_matches (error, G_IO_ERROR, G_IO_ERROR_CANCELLED))
    {
      g_error_free (error);
      return;
    }
  self->in_flight = FALSE;
  if (!ret)
    {
      g_debug ("maluos gpus: GetState: %s", error ? error->message : "?");
      g_free (self->last_error);
      self->last_error = g_strdup (error ? error->message : "GetState failed");
      g_clear_error (&error);
      adw_banner_set_revealed (ADW_BANNER (self->banner), self->answered_once);
      if (!self->answered_once)
        set_available (self, FALSE);
      self_test_done (self, FALSE);   /* a self-test ends on the first refused call (no service: ServiceUnknown) */
      return;
    }

  const char *json = NULL;
  g_variant_get (ret, "(&s)", &json);
  JsonParser *parser = json_parser_new ();
  if (json_parser_load_from_data (parser, json, -1, &error) && JSON_NODE_HOLDS_OBJECT (json_parser_get_root (parser)))
    {
      apply_state (self, json_node_get_object (json_parser_get_root (parser)));
      self->answered_once = TRUE;
      adw_banner_set_revealed (ADW_BANNER (self->banner), FALSE);
      set_available (self, TRUE);
      self_test_done (self, TRUE);
    }
  else
    {
      g_warning ("maluos gpus: state is not JSON: %s", error ? error->message : "?");
      g_clear_error (&error);
    }
  g_object_unref (parser);
  g_variant_unref (ret);
}

static void
on_proxy (GObject *, GAsyncResult *res, gpointer data)
{
  GsmMaluosGpusView *self = (GsmMaluosGpusView *) data;
  GError *error = NULL;
  GDBusProxy *proxy = g_dbus_proxy_new_for_bus_finish (res, &error);

  if (g_error_matches (error, G_IO_ERROR, G_IO_ERROR_CANCELLED))
    {
      g_error_free (error);
      return;
    }
  if (!proxy)
    {
      g_debug ("maluos gpus: no session proxy: %s", error ? error->message : "?");
      g_free (self->last_error);
      self->last_error = g_strdup_printf ("no session bus: %s", error ? error->message : "?");
      g_clear_error (&error);
      self->in_flight = FALSE;
      self_test_done (self, FALSE);
      return;
    }
  self->proxy = proxy;
  self->in_flight = FALSE;
  maluos_gpus_update (self);
}

void
maluos_gpus_update (GsmMaluosGpusView *self)
{
  if (self->in_flight)
    return;
  self->in_flight = TRUE;
  if (!self->proxy)
    {
      g_dbus_proxy_new_for_bus (G_BUS_TYPE_SESSION, G_DBUS_PROXY_FLAGS_DO_NOT_LOAD_PROPERTIES, NULL,
                                SESSION_NAME, SESSION_PATH, SESSION_IFACE, self->cancellable, on_proxy, self);
      return;
    }
  g_dbus_proxy_call (self->proxy, "GetState", NULL, G_DBUS_CALL_FLAGS_NONE, 30000, self->cancellable, on_state, self);
}

static gboolean
cb_timeout (gpointer data)
{
  maluos_gpus_update ((GsmMaluosGpusView *) data);
  return G_SOURCE_CONTINUE;
}

void
maluos_gpus_freeze (GsmMaluosGpusView *self)
{
  if (self->timeout)
    {
      g_source_remove (self->timeout);
      self->timeout = 0;
    }
}

void
maluos_gpus_thaw (GsmMaluosGpusView *self)
{
  if (self->timeout)
    return;
  maluos_gpus_update (self);
  self->timeout = g_timeout_add (self->interval_ms, cb_timeout, self);
}

gboolean
gsm_maluos_gpus_view_get_available (GsmMaluosGpusView *self)
{
  return self->available;
}

/* The self-test runs on slow machines (the boot test under TCG): the window's first paint can hold the main
 * loop for longer than any sensible deadline, and when the loop resumes the timer and the D-Bus reply are
 * both ready.  So the timer never fails a call that is still in flight (the call's own 30 s timeout ends it
 * with an error, which fails the test with its message); it only fails when nothing is pending past the
 * deadline. */
static gboolean
cb_self_test_timeout (gpointer data)
{
  GsmMaluosGpusView *self = (GsmMaluosGpusView *) data;
  self->self_test_timeout = 0;
  if (!self->self_test)
    return G_SOURCE_REMOVE;
  if (self->in_flight || g_get_monotonic_time () < self->self_test_deadline)
    {
      self->self_test_timeout = g_timeout_add_seconds (5, cb_self_test_timeout, self);
      return G_SOURCE_REMOVE;
    }
  self_test_done (self, FALSE);
  return G_SOURCE_REMOVE;
}

void
gsm_maluos_gpus_view_self_test (GsmMaluosGpusView *self)
{
  self->self_test = TRUE;
  self->self_test_deadline = g_get_monotonic_time () + 60 * G_USEC_PER_SEC;
  self->self_test_timeout = g_timeout_add_seconds (20, cb_self_test_timeout, self);
  maluos_gpus_update (self);
}

/* ---- the one action: the sharing switch runs maluctl through polkit */

static void
on_share_done (GObject *source, GAsyncResult *res, gpointer data)
{
  GsmMaluosGpusView *self = (GsmMaluosGpusView *) data;
  GError *error = NULL;

  if (!g_subprocess_wait_check_finish (G_SUBPROCESS (source), res, &error))
    {
      g_warning ("maluos gpus: maluctl gateway share: %s", error ? error->message : "?");
      g_clear_error (&error);
    }
  gtk_widget_set_sensitive (self->share_row, TRUE);
  maluos_gpus_update (self);
  g_object_unref (self);
}

static void
on_share_toggled (GObject *, GParamSpec *, gpointer data)
{
  GsmMaluosGpusView *self = (GsmMaluosGpusView *) data;
  GError *error = NULL;

  if (self->updating_switch)
    return;
  gboolean on = adw_switch_row_get_active (ADW_SWITCH_ROW (self->share_row));
  const char *argv[] = { "pkexec", "maluctl", "gateway", "share", on ? "on" : "off", NULL };
  GSubprocess *p = g_subprocess_newv (argv, G_SUBPROCESS_FLAGS_STDOUT_SILENCE, &error);
  if (!p)
    {
      g_warning ("maluos gpus: pkexec: %s", error ? error->message : "?");
      g_clear_error (&error);
      maluos_gpus_update (self);
      return;
    }
  gtk_widget_set_sensitive (self->share_row, FALSE);
  g_subprocess_wait_check_async (p, NULL, on_share_done, g_object_ref (self));
  g_object_unref (p);
}

/* ---- GObject */

static void
gsm_maluos_gpus_view_get_property (GObject *object, guint prop_id, GValue *value, GParamSpec *pspec)
{
  GsmMaluosGpusView *self = GSM_MALUOS_GPUS_VIEW (object);
  switch (prop_id)
    {
    case PROP_AVAILABLE:
      g_value_set_boolean (value, self->available);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
    }
}

static void
gsm_maluos_gpus_view_dispose (GObject *object)
{
  GsmMaluosGpusView *self = GSM_MALUOS_GPUS_VIEW (object);

  maluos_gpus_freeze (self);
  if (self->self_test_timeout)
    {
      g_source_remove (self->self_test_timeout);
      self->self_test_timeout = 0;
    }
  if (self->cancellable)
    {
      g_cancellable_cancel (self->cancellable);
      g_clear_object (&self->cancellable);
    }
  g_clear_object (&self->proxy);
  g_clear_pointer (&self->last_error, g_free);
  if (self->rows)
    {
      g_ptr_array_free (self->rows, TRUE);
      self->rows = NULL;
    }
  g_clear_pointer (&self->box, gtk_widget_unparent);
  g_clear_pointer (&self->summary, g_free);

  G_OBJECT_CLASS (gsm_maluos_gpus_view_parent_class)->dispose (object);
}

static void
gsm_maluos_gpus_view_class_init (GsmMaluosGpusViewClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (klass);

  object_class->dispose = gsm_maluos_gpus_view_dispose;
  object_class->get_property = gsm_maluos_gpus_view_get_property;

  properties[PROP_AVAILABLE] = g_param_spec_boolean ("available", NULL, NULL, FALSE,
                                                     (GParamFlags) (G_PARAM_READABLE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_properties (object_class, N_PROPS, properties);

  gtk_widget_class_set_layout_manager_type (widget_class, GTK_TYPE_BIN_LAYOUT);
}

static void
gsm_maluos_gpus_view_init (GsmMaluosGpusView *self)
{
  self->interval_ms = 2000;
  self->rows = g_ptr_array_new_with_free_func (gpu_row_free);
  self->cancellable = g_cancellable_new ();

  self->box = gtk_box_new (GTK_ORIENTATION_VERTICAL, 0);
  gtk_widget_set_parent (self->box, GTK_WIDGET (self));

  self->banner = adw_banner_new (_("The MaluOS session service is not answering"));
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

  /* one probe at construction, whatever tab is current: it decides whether the tab is shown */
  maluos_gpus_update (self);
}

GsmMaluosGpusView *
gsm_maluos_gpus_view_new (void)
{
  return GSM_MALUOS_GPUS_VIEW (g_object_new (GSM_TYPE_MALUOS_GPUS_VIEW, NULL));
}
