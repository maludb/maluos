/* MaluOS: the session client shared by the MaluOS tabs. See maluos-session.h and README.maluos.md. */
#include <config.h>

#include <gio/gio.h>
#include <glib/gi18n.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "maluos-session.h"

#define SESSION_NAME  "com.maluos.Session"
#define SESSION_PATH  "/com/maluos/Session"
#define SESSION_IFACE "com.maluos.Session1"

struct _GsmMaluosSession
{
  GObject parent_instance;

  GDBusProxy   *proxy;
  GCancellable *cancellable;
  guint         timeout;
  guint         interval_ms;
  int           watchers_state;
  int           watchers_queue;
  gboolean      proxy_in_flight;
  gboolean      state_in_flight;
  gboolean      queue_in_flight;
  gboolean      available;
  gboolean      stale;
  gboolean      answered_once;
  JsonParser   *state_parser;      /* owns the last state */
  JsonObject   *state;
  char         *last_error;

  gboolean      self_test;
  gboolean      self_test_state_ok;
  gboolean      self_test_queue_done;
  guint         self_test_timeout;
  gint64        self_test_deadline;   /* monotonic µs */
  GHashTable   *summaries;            /* tab -> one line, for the self-test */
};

G_DEFINE_FINAL_TYPE (GsmMaluosSession, gsm_maluos_session, G_TYPE_OBJECT)

enum {
  PROP_0,
  PROP_AVAILABLE,
  PROP_STALE,
  N_PROPS
};

enum {
  SIG_STATE,
  SIG_QUEUE,
  N_SIGNALS
};

static GParamSpec *properties[N_PROPS];
static guint signals[N_SIGNALS];
static GsmMaluosSession *the_session;

/* ---- JSON helpers */

JsonObject *
gsm_maluos_jo (JsonObject *o, const char *name)
{
  if (!o || !json_object_has_member (o, name))
    return NULL;
  JsonNode *n = json_object_get_member (o, name);
  return JSON_NODE_HOLDS_OBJECT (n) ? json_node_get_object (n) : NULL;
}

JsonArray *
gsm_maluos_ja (JsonObject *o, const char *name)
{
  if (!o || !json_object_has_member (o, name))
    return NULL;
  JsonNode *n = json_object_get_member (o, name);
  return JSON_NODE_HOLDS_ARRAY (n) ? json_node_get_array (n) : NULL;
}

const char *
gsm_maluos_js (JsonObject *o, const char *name)
{
  if (!o || !json_object_has_member (o, name))
    return NULL;
  JsonNode *n = json_object_get_member (o, name);
  if (!JSON_NODE_HOLDS_VALUE (n) || json_node_get_value_type (n) != G_TYPE_STRING)
    return NULL;
  return json_node_get_string (n);
}

gboolean
gsm_maluos_jd (JsonObject *o, const char *name, double *out)
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

gboolean
gsm_maluos_jb (JsonObject *o, const char *name)
{
  if (!o || !json_object_has_member (o, name))
    return FALSE;
  JsonNode *n = json_object_get_member (o, name);
  return JSON_NODE_HOLDS_VALUE (n) && json_node_get_value_type (n) == G_TYPE_BOOLEAN && json_node_get_boolean (n);
}

/* ---- properties */

static void
set_flag (GsmMaluosSession *self, gboolean *field, gboolean value, GParamSpec *pspec)
{
  if (*field == value)
    return;
  *field = value;
  g_object_notify_by_pspec (G_OBJECT (self), pspec);
}

gboolean
gsm_maluos_session_get_available (GsmMaluosSession *self)
{
  return self->available;
}

JsonObject *
gsm_maluos_session_get_state (GsmMaluosSession *self)
{
  return self->state;
}

/* ---- the self-test */

void
gsm_maluos_session_set_summary (GsmMaluosSession *self, const char *tab, const char *summary)
{
  g_hash_table_insert (self->summaries, g_strdup (tab), g_strdup (summary ? summary : "no summary"));
}

static const char *
summary (GsmMaluosSession *self, const char *tab)
{
  const char *s = (const char *) g_hash_table_lookup (self->summaries, tab);
  return s ? s : "no summary";
}

static void
self_test_done (GsmMaluosSession *self, gboolean ok)
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
    g_print ("self-test ok: GPUs: %s; Network: %s; Queue: %s\n",
             summary (self, "gpus"), summary (self, "network"), summary (self, "queue"));
  else
    g_print ("self-test FAIL: the MaluOS session service did not answer%s%s\n",
             self->last_error ? ": " : "", self->last_error ? self->last_error : "");
  fflush (stdout);
  exit (ok ? 0 : 1);
}

static void
self_test_check (GsmMaluosSession *self)
{
  if (self->self_test && self->self_test_state_ok && self->self_test_queue_done)
    self_test_done (self, TRUE);
}

/* The self-test runs on slow machines (the boot test under TCG): the window's first paint can hold the main
 * loop for longer than any sensible deadline, and when the loop resumes the timer and the D-Bus reply are
 * both ready.  So the timer never fails a call that is still in flight (the call's own 30 s timeout ends it
 * with an error, which fails the test with its message); it only fails when nothing is pending past the
 * deadline. */
static gboolean
cb_self_test_timeout (gpointer data)
{
  GsmMaluosSession *self = (GsmMaluosSession *) data;
  self->self_test_timeout = 0;
  if (!self->self_test)
    return G_SOURCE_REMOVE;
  if (self->proxy_in_flight || self->state_in_flight || self->queue_in_flight || g_get_monotonic_time () < self->self_test_deadline)
    {
      self->self_test_timeout = g_timeout_add_seconds (5, cb_self_test_timeout, self);
      return G_SOURCE_REMOVE;
    }
  self_test_done (self, FALSE);
  return G_SOURCE_REMOVE;
}

void
gsm_maluos_session_self_test (GsmMaluosSession *self)
{
  self->self_test = TRUE;
  self->self_test_deadline = g_get_monotonic_time () + 60 * G_USEC_PER_SEC;
  self->self_test_timeout = g_timeout_add_seconds (20, cb_self_test_timeout, self);
  gsm_maluos_session_update (self);
}

/* ---- the calls */

static void tick (GsmMaluosSession *self);

static void
on_state (GObject *source, GAsyncResult *res, gpointer data)
{
  GsmMaluosSession *self = (GsmMaluosSession *) data;
  GError *error = NULL;
  GVariant *ret = g_dbus_proxy_call_finish (G_DBUS_PROXY (source), res, &error);

  if (g_error_matches (error, G_IO_ERROR, G_IO_ERROR_CANCELLED))
    {
      g_error_free (error);
      return;
    }
  self->state_in_flight = FALSE;
  if (!ret)
    {
      g_debug ("maluos session: GetState: %s", error ? error->message : "?");
      g_free (self->last_error);
      self->last_error = g_strdup (error ? error->message : "GetState failed");
      g_clear_error (&error);
      set_flag (self, &self->stale, self->answered_once, properties[PROP_STALE]);
      self_test_done (self, FALSE);   /* a self-test ends on the first refused call (no service: ServiceUnknown) */
      return;
    }

  const char *json = NULL;
  g_variant_get (ret, "(&s)", &json);
  JsonParser *parser = json_parser_new ();
  if (json_parser_load_from_data (parser, json, -1, &error) && JSON_NODE_HOLDS_OBJECT (json_parser_get_root (parser)))
    {
      g_clear_object (&self->state_parser);
      self->state_parser = parser;
      self->state = json_node_get_object (json_parser_get_root (parser));
      self->answered_once = TRUE;
      set_flag (self, &self->stale, FALSE, properties[PROP_STALE]);
      set_flag (self, &self->available, TRUE, properties[PROP_AVAILABLE]);
      g_signal_emit (self, signals[SIG_STATE], 0, self->state);
      self->self_test_state_ok = TRUE;
      self_test_check (self);
    }
  else
    {
      g_warning ("maluos session: state is not JSON: %s", error ? error->message : "?");
      g_clear_error (&error);
      g_object_unref (parser);
    }
  g_variant_unref (ret);
}

static void
on_queue (GObject *source, GAsyncResult *res, gpointer data)
{
  GsmMaluosSession *self = (GsmMaluosSession *) data;
  GError *error = NULL;
  GVariant *ret = g_dbus_proxy_call_finish (G_DBUS_PROXY (source), res, &error);

  if (g_error_matches (error, G_IO_ERROR, G_IO_ERROR_CANCELLED))
    {
      g_error_free (error);
      return;
    }
  self->queue_in_flight = FALSE;
  if (!ret)
    {
      /* an older session service has no NodeQueue (UnknownMethod): the Queue tab says so; the self-test goes on */
      char *msg = g_strdup (error ? error->message : "NodeQueue failed");
      g_debug ("maluos session: NodeQueue: %s", msg);
      g_clear_error (&error);
      g_signal_emit (self, signals[SIG_QUEUE], 0, NULL, msg);
      g_free (msg);
      self->self_test_queue_done = TRUE;
      self_test_check (self);
      return;
    }
  const char *json = NULL;
  g_variant_get (ret, "(&s)", &json);
  JsonParser *parser = json_parser_new ();
  if (json_parser_load_from_data (parser, json, -1, &error) && JSON_NODE_HOLDS_OBJECT (json_parser_get_root (parser)))
    g_signal_emit (self, signals[SIG_QUEUE], 0, json_node_get_object (json_parser_get_root (parser)), NULL);
  else
    {
      g_warning ("maluos session: queue is not JSON: %s", error ? error->message : "?");
      g_signal_emit (self, signals[SIG_QUEUE], 0, NULL, "the queue answer is not JSON");
      g_clear_error (&error);
    }
  g_object_unref (parser);
  g_variant_unref (ret);
  self->self_test_queue_done = TRUE;
  self_test_check (self);
}

static void
on_proxy (GObject *, GAsyncResult *res, gpointer data)
{
  GsmMaluosSession *self = (GsmMaluosSession *) data;
  GError *error = NULL;
  GDBusProxy *proxy = g_dbus_proxy_new_for_bus_finish (res, &error);

  if (g_error_matches (error, G_IO_ERROR, G_IO_ERROR_CANCELLED))
    {
      g_error_free (error);
      return;
    }
  self->proxy_in_flight = FALSE;
  if (!proxy)
    {
      g_debug ("maluos session: no session proxy: %s", error ? error->message : "?");
      g_free (self->last_error);
      self->last_error = g_strdup_printf ("no session bus: %s", error ? error->message : "?");
      g_clear_error (&error);
      self_test_done (self, FALSE);
      return;
    }
  self->proxy = proxy;
  tick (self);
}

static void
tick (GsmMaluosSession *self)
{
  if (!self->proxy)
    {
      if (self->proxy_in_flight)
        return;
      self->proxy_in_flight = TRUE;
      g_dbus_proxy_new_for_bus (G_BUS_TYPE_SESSION, G_DBUS_PROXY_FLAGS_DO_NOT_LOAD_PROPERTIES, NULL,
                                SESSION_NAME, SESSION_PATH, SESSION_IFACE, self->cancellable, on_proxy, self);
      return;
    }
  if ((self->watchers_state > 0 || self->self_test || !self->answered_once) && !self->state_in_flight)
    {
      self->state_in_flight = TRUE;
      g_dbus_proxy_call (self->proxy, "GetState", NULL, G_DBUS_CALL_FLAGS_NONE, 30000, self->cancellable, on_state, self);
    }
  if ((self->watchers_queue > 0 || self->self_test) && !self->queue_in_flight)
    {
      self->queue_in_flight = TRUE;
      g_dbus_proxy_call (self->proxy, "NodeQueue", NULL, G_DBUS_CALL_FLAGS_NONE, 30000, self->cancellable, on_queue, self);
    }
}

void
gsm_maluos_session_update (GsmMaluosSession *self)
{
  tick (self);
}

static gboolean
cb_timeout (gpointer data)
{
  tick ((GsmMaluosSession *) data);
  return G_SOURCE_CONTINUE;
}

void
gsm_maluos_session_watch (GsmMaluosSession *self, GsmMaluosWatch what)
{
  if (what & GSM_MALUOS_WATCH_STATE)
    self->watchers_state++;
  if (what & GSM_MALUOS_WATCH_QUEUE)
    self->watchers_queue++;
  tick (self);
  if (!self->timeout)
    self->timeout = g_timeout_add (self->interval_ms, cb_timeout, self);
}

void
gsm_maluos_session_unwatch (GsmMaluosSession *self, GsmMaluosWatch what)
{
  if ((what & GSM_MALUOS_WATCH_STATE) && self->watchers_state > 0)
    self->watchers_state--;
  if ((what & GSM_MALUOS_WATCH_QUEUE) && self->watchers_queue > 0)
    self->watchers_queue--;
  if (self->watchers_state == 0 && self->watchers_queue == 0 && self->timeout)
    {
      g_source_remove (self->timeout);
      self->timeout = 0;
    }
}

/* ---- running maluctl */

typedef struct
{
  GsmMaluosRunDone done;
  gpointer         data;
} Run;

static char *
last_line (const char *text)
{
  if (!text)
    return NULL;
  char **lines = g_strsplit (text, "\n", -1);
  char *out = NULL;
  for (int i = 0; lines[i]; i++)
    if (*g_strstrip (lines[i]))
      {
        g_free (out);
        out = g_strdup (lines[i]);
      }
  g_strfreev (lines);
  return out;
}

static void
on_run_done (GObject *source, GAsyncResult *res, gpointer data)
{
  Run *run = (Run *) data;
  GSubprocess *p = G_SUBPROCESS (source);
  GError *error = NULL;
  char *out = NULL, *err = NULL;
  gboolean ok = g_subprocess_communicate_utf8_finish (p, res, &out, &err, &error) && g_subprocess_get_successful (p);
  char *line = ok ? last_line (out) : last_line (err && *err ? err : out);
  if (!ok && !line)
    line = g_strdup (error ? error->message : "failed");
  g_clear_error (&error);
  run->done (ok, line ? line : "", run->data);
  g_free (line);
  g_free (out);
  g_free (err);
  g_free (run);
}

void
gsm_maluos_run (const char *const *argv, GsmMaluosRunDone done, gpointer data)
{
  GError *error = NULL;
  GSubprocess *p = g_subprocess_newv (argv, (GSubprocessFlags) (G_SUBPROCESS_FLAGS_STDOUT_PIPE | G_SUBPROCESS_FLAGS_STDERR_PIPE), &error);
  if (!p)
    {
      done (FALSE, error ? error->message : "cannot run", data);
      g_clear_error (&error);
      return;
    }
  Run *run = g_new0 (Run, 1);
  run->done = done;
  run->data = data;
  g_subprocess_communicate_utf8_async (p, NULL, NULL, on_run_done, run);
  g_object_unref (p);
}

/* ---- GObject */

static void
gsm_maluos_session_get_property (GObject *object, guint prop_id, GValue *value, GParamSpec *pspec)
{
  GsmMaluosSession *self = GSM_MALUOS_SESSION (object);
  switch (prop_id)
    {
    case PROP_AVAILABLE:
      g_value_set_boolean (value, self->available);
      break;
    case PROP_STALE:
      g_value_set_boolean (value, self->stale);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
    }
}

static void
gsm_maluos_session_dispose (GObject *object)
{
  GsmMaluosSession *self = GSM_MALUOS_SESSION (object);

  if (self->timeout)
    {
      g_source_remove (self->timeout);
      self->timeout = 0;
    }
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
  self->state = NULL;
  g_clear_object (&self->state_parser);
  g_clear_pointer (&self->last_error, g_free);
  g_clear_pointer (&self->summaries, g_hash_table_unref);

  G_OBJECT_CLASS (gsm_maluos_session_parent_class)->dispose (object);
}

static void
gsm_maluos_session_class_init (GsmMaluosSessionClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);

  object_class->dispose = gsm_maluos_session_dispose;
  object_class->get_property = gsm_maluos_session_get_property;

  properties[PROP_AVAILABLE] = g_param_spec_boolean ("available", NULL, NULL, FALSE,
                                                     (GParamFlags) (G_PARAM_READABLE | G_PARAM_STATIC_STRINGS));
  properties[PROP_STALE] = g_param_spec_boolean ("stale", NULL, NULL, FALSE,
                                                 (GParamFlags) (G_PARAM_READABLE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_properties (object_class, N_PROPS, properties);

  signals[SIG_STATE] = g_signal_new ("state", G_TYPE_FROM_CLASS (klass), G_SIGNAL_RUN_LAST, 0, NULL, NULL, NULL,
                                     G_TYPE_NONE, 1, G_TYPE_POINTER);
  signals[SIG_QUEUE] = g_signal_new ("queue", G_TYPE_FROM_CLASS (klass), G_SIGNAL_RUN_LAST, 0, NULL, NULL, NULL,
                                     G_TYPE_NONE, 2, G_TYPE_POINTER, G_TYPE_STRING);
}

static void
gsm_maluos_session_init (GsmMaluosSession *self)
{
  self->interval_ms = 2000;
  self->cancellable = g_cancellable_new ();
  self->summaries = g_hash_table_new_full (g_str_hash, g_str_equal, g_free, g_free);
}

GsmMaluosSession *
gsm_maluos_session_get (void)
{
  if (!the_session)
    {
      the_session = GSM_MALUOS_SESSION (g_object_new (GSM_TYPE_MALUOS_SESSION, NULL));
      /* one probe at creation, whatever tab is current: it decides whether the MaluOS tabs are shown */
      tick (the_session);
    }
  return the_session;
}
