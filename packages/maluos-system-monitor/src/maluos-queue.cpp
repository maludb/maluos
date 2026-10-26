/* MaluOS: the Queue tab. See maluos-queue.h and README.maluos.md. */
#include <config.h>

#include <adwaita.h>
#include <glib/gi18n.h>
#include <json-glib/json-glib.h>
#include <string.h>

#include "maluos-queue.h"
#include "maluos-session.h"

#define jo gsm_maluos_jo
#define ja gsm_maluos_ja
#define js gsm_maluos_js
#define jd gsm_maluos_jd
#define jb gsm_maluos_jb

typedef struct _GsmMaluosQueueView GsmMaluosQueueView;

typedef struct
{
  GsmMaluosQueueView *view;
  GtkWidget          *row;
  GtkWidget          *button;   /* Pause / Resume */
  char               *name;
  gboolean            paused;
} LaneRow;

typedef struct
{
  GsmMaluosQueueView *view;
  GtkWidget          *row;
  GtkWidget          *drop;     /* the class */
  GtkWidget          *cancel;
  GtkStringList      *classes;
  char               *id;
  char               *lane;
  gboolean            queued;
  gboolean            updating;
} JobRow;

typedef struct
{
  GsmMaluosQueueView *view;
  char               *label;
} Action;

struct _GsmMaluosQueueView
{
  GtkWidget parent_instance;

  GtkWidget *overlay;        /* AdwToastOverlay */
  GtkWidget *box;
  GtkWidget *banner;
  GtkWidget *page;
  GtkWidget *lanes_group;
  GtkWidget *note_row;       /* why there is nothing to show */
  GtkWidget *queue_group;
  GtkWidget *empty_row;
  GtkWidget *more_group;
  GtkWidget *manager_row;

  GPtrArray *lane_rows;
  GPtrArray *job_rows;
  char      *office_url;

  GsmMaluosSession *session;
  gulong            state_id;
  gulong            queue_id;
  gboolean          watching;
};

G_DEFINE_FINAL_TYPE (GsmMaluosQueueView, gsm_maluos_queue_view, GTK_TYPE_WIDGET)

/* ---- helpers */

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

static void
join (GString *s, const char *text)
{
  if (s->len)
    g_string_append (s, " · ");
  g_string_append (s, text);
}

static char *
ms_text (double ms)
{
  if (ms < 1000)
    return g_strdup_printf (_("%.0f ms"), ms);
  if (ms < 60000)
    return g_strdup_printf (_("%.1f s"), ms / 1000);
  return g_strdup_printf (_("%.0f min"), ms / 60000);
}

static void
toast (GsmMaluosQueueView *self, const char *text)
{
  AdwToast *t = adw_toast_new (text && *text ? text : "…");
  adw_toast_set_timeout (t, 4);
  adw_toast_overlay_add_toast (ADW_TOAST_OVERLAY (self->overlay), t);
}

/* ---- actions: maluctl gateway node … as this user (an operator) */

static void
on_action_done (gboolean ok, const char *output, gpointer data)
{
  Action *a = (Action *) data;
  char *text = g_strdup_printf ("%s: %s", a->label, output && *output ? output : (ok ? _("done") : _("failed")));
  if (!ok)
    g_warning ("maluos queue: %s", text);
  toast (a->view, text);
  g_free (text);
  gsm_maluos_session_update (a->view->session);
  g_object_unref (a->view);
  g_free (a->label);
  g_free (a);
}

static void
run_node (GsmMaluosQueueView *self, const char *label, const char *verb, const char *arg1, const char *arg2)
{
  const char *argv[] = { "maluctl", "gateway", "node", verb, arg1, arg2, NULL };
  Action *a = g_new0 (Action, 1);
  a->view = (GsmMaluosQueueView *) g_object_ref (self);
  a->label = g_strdup (label);
  gsm_maluos_run (argv, on_action_done, a);
}

static void
on_lane_clicked (GtkButton *, gpointer data)
{
  LaneRow *r = (LaneRow *) data;
  char *label = g_strdup_printf ("%s %s", r->paused ? _("Resume") : _("Pause"), r->name);
  gtk_widget_set_sensitive (r->button, FALSE);
  run_node (r->view, label, r->paused ? "resume" : "pause", r->name, NULL);
  g_free (label);
}

static void
on_cancel_clicked (GtkButton *, gpointer data)
{
  JobRow *r = (JobRow *) data;
  char *label = g_strdup_printf (_("Cancel %s"), r->id);
  gtk_widget_set_sensitive (r->cancel, FALSE);
  run_node (r->view, label, "cancel", r->id, NULL);
  g_free (label);
}

static void
on_class_selected (GObject *, GParamSpec *, gpointer data)
{
  JobRow *r = (JobRow *) data;
  if (r->updating || !r->queued)
    return;
  guint i = gtk_drop_down_get_selected (GTK_DROP_DOWN (r->drop));
  const char *cls = i == GTK_INVALID_LIST_POSITION ? NULL : gtk_string_list_get_string (r->classes, i);
  if (!cls)
    return;
  char *label = g_strdup_printf (_("Move %s to %s"), r->id, cls);
  gtk_widget_set_sensitive (r->drop, FALSE);
  run_node (r->view, label, "priority", r->id, cls);
  g_free (label);
}

/* ---- the lanes */

static void
lane_row_free (gpointer data)
{
  LaneRow *r = (LaneRow *) data;
  g_free (r->name);
  g_free (r);
}

static LaneRow *
lane_row_new (GsmMaluosQueueView *self, const char *name)
{
  LaneRow *r = g_new0 (LaneRow, 1);
  r->view = self;
  r->name = g_strdup (name);
  r->row = action_row (name, NULL);
  gtk_widget_add_css_class (r->row, "property");
  r->button = gtk_button_new_with_label (_("Pause"));
  gtk_widget_set_valign (r->button, GTK_ALIGN_CENTER);
  g_signal_connect (r->button, "clicked", G_CALLBACK (on_lane_clicked), r);
  adw_action_row_add_suffix (ADW_ACTION_ROW (r->row), r->button);
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->lanes_group), r->row);
  return r;
}

static void
lane_row_update (LaneRow *r, JsonObject *lane)
{
  GString *s = g_string_new (NULL);
  double cap = 0, running = 0, queued = 0, oldest = 0;
  jd (lane, "capacity", &cap);
  jd (lane, "running", &running);
  jd (lane, "queued", &queued);
  jd (lane, "oldest_queued_ms", &oldest);

  join (s, js (lane, "kind") ? js (lane, "kind") : "?");
  if (lane && json_object_has_member (lane, "healthy") && !jb (lane, "healthy"))
    join (s, _("unhealthy"));
  {
    char *t = g_strdup_printf (_("%.0f of %.0f running"), running, cap);
    join (s, t);
    g_free (t);
  }
  {
    char *t;
    if (queued > 0)
      {
        char *o = ms_text (oldest);
        t = g_strdup_printf (_("%.0f queued, the oldest for %s"), queued, o);
        g_free (o);
      }
    else
      t = g_strdup (_("none queued"));
    join (s, t);
    g_free (t);
  }
  if (js (lane, "resident"))
    {
      char *t = g_strdup_printf (_("resident %s"), js (lane, "resident"));
      join (s, t);
      g_free (t);
    }
  JsonObject *classes = jo (lane, "classes");
  GList *names = classes ? json_object_get_members (classes) : NULL;
  GString *waits = g_string_new (NULL);
  for (GList *l = names; l; l = l->next)
    {
      JsonObject *c = jo (classes, (const char *) l->data);
      double w = 0, q = 0;
      jd (c, "expected_wait_ms", &w);
      jd (c, "queued", &q);
      if (q <= 0 && w <= 0)
        continue;
      char *wt = ms_text (w);
      if (waits->len)
        g_string_append (waits, ", ");
      g_string_append_printf (waits, "%s %.0f (%s)", (const char *) l->data, q, wt);
      g_free (wt);
    }
  g_list_free (names);
  if (waits->len)
    {
      char *t = g_strdup_printf (_("by class: %s"), waits->str);
      join (s, t);
      g_free (t);
    }
  g_string_free (waits, TRUE);

  r->paused = jb (lane, "paused");
  if (r->paused)
    join (s, _("PAUSED: nothing is dispatched; queued calls wait"));
  set_subtitle (r->row, s->str);
  g_string_free (s, TRUE);
  gtk_button_set_label (GTK_BUTTON (r->button), r->paused ? _("Resume") : _("Pause"));
  gtk_widget_set_sensitive (r->button, TRUE);
}

static void
apply_lanes (GsmMaluosQueueView *self, JsonObject *lanes)
{
  GList *names = lanes ? json_object_get_members (lanes) : NULL;
  guint n = g_list_length (names);
  gboolean same = (n == self->lane_rows->len);
  guint i = 0;
  for (GList *l = names; same && l; l = l->next, i++)
    same = g_strcmp0 ((const char *) l->data, ((LaneRow *) g_ptr_array_index (self->lane_rows, i))->name) == 0;
  if (!same)
    {
      for (i = 0; i < self->lane_rows->len; i++)
        adw_preferences_group_remove (ADW_PREFERENCES_GROUP (self->lanes_group), ((LaneRow *) g_ptr_array_index (self->lane_rows, i))->row);
      g_ptr_array_set_size (self->lane_rows, 0);
      for (GList *l = names; l; l = l->next)
        g_ptr_array_add (self->lane_rows, lane_row_new (self, (const char *) l->data));
    }
  i = 0;
  for (GList *l = names; l; l = l->next, i++)
    lane_row_update ((LaneRow *) g_ptr_array_index (self->lane_rows, i), jo (lanes, (const char *) l->data));
  g_list_free (names);
}

/* ---- the jobs */

static void
job_row_free (gpointer data)
{
  JobRow *r = (JobRow *) data;
  g_clear_object (&r->classes);
  g_free (r->id);
  g_free (r->lane);
  g_free (r);
}

static JobRow *
job_row_new (GsmMaluosQueueView *self, JsonObject *j)
{
  JobRow *r = g_new0 (JobRow, 1);
  r->view = self;
  r->id = g_strdup (js (j, "id") ? js (j, "id") : "?");
  r->lane = g_strdup (js (j, "lane") ? js (j, "lane") : "");
  r->row = action_row (r->id, NULL);
  gtk_widget_add_css_class (r->row, "property");

  GtkWidget *suffix = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 8);
  gtk_widget_set_valign (suffix, GTK_ALIGN_CENTER);
  r->classes = gtk_string_list_new (NULL);
  r->drop = gtk_drop_down_new (G_LIST_MODEL (g_object_ref (r->classes)), NULL);
  gtk_widget_set_valign (r->drop, GTK_ALIGN_CENTER);
  gtk_widget_set_tooltip_text (r->drop, _("The class: its priority and its share of the lane (maluctl gateway node priority)"));
  g_signal_connect (r->drop, "notify::selected", G_CALLBACK (on_class_selected), r);
  gtk_box_append (GTK_BOX (suffix), r->drop);
  r->cancel = gtk_button_new_with_label (_("Cancel"));
  gtk_widget_set_valign (r->cancel, GTK_ALIGN_CENTER);
  gtk_widget_add_css_class (r->cancel, "destructive-action");
  gtk_widget_set_tooltip_text (r->cancel, _("Cancel this call: a queued one leaves the queue, a running one is aborted (its caller gets 409 cancelled)"));
  g_signal_connect (r->cancel, "clicked", G_CALLBACK (on_cancel_clicked), r);
  gtk_box_append (GTK_BOX (suffix), r->cancel);
  adw_action_row_add_suffix (ADW_ACTION_ROW (r->row), suffix);

  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->queue_group), r->row);
  return r;
}

static void
job_row_update (JobRow *r, JsonObject *j, JsonObject *lanes)
{
  const char *model = js (j, "model");
  const char *requested = js (j, "requested_model");
  const char *cls = js (j, "class");
  const char *state = js (j, "state");
  double v;

  /* title: the model (requested → served when they differ) */
  {
    char *t = requested && model && g_strcmp0 (requested, model) != 0 ? g_strdup_printf ("%s → %s", requested, model)
            : g_strdup (model ? model : (requested ? requested : r->id));
    set_title (r->row, t);
    g_free (t);
  }
  r->queued = g_strcmp0 (state, "queued") == 0;

  GString *s = g_string_new (NULL);
  join (s, r->queued ? _("queued") : _("running"));
  if (js (j, "principal"))
    join (s, js (j, "principal"));
  if (js (j, "key"))
    {
      char *t = g_strdup_printf (_("key %s"), js (j, "key"));
      join (s, t);
      g_free (t);
    }
  {
    GString *how = g_string_new (NULL);
    if (js (j, "face"))
      g_string_append (how, js (j, "face"));
    if (js (j, "kind"))
      g_string_append_printf (how, "%s%s", how->len ? " " : "", js (j, "kind"));
    if (g_strcmp0 (js (j, "mode"), "async") == 0)
      g_string_append (how, _(", async"));
    if (how->len)
      join (s, how->str);
    g_string_free (how, TRUE);
  }
  if (r->queued && jd (j, "waited_ms", &v))
    {
      char *w = ms_text (v), *t = g_strdup_printf (_("waiting %s"), w);
      join (s, t);
      g_free (t);
      g_free (w);
      if (jd (j, "expected_wait_ms", &v) && v > 0)
        {
          w = ms_text (v);
          t = g_strdup_printf (_("about %s to go"), w);
          join (s, t);
          g_free (t);
          g_free (w);
        }
    }
  else if (jd (j, "elapsed_ms", &v))
    {
      char *w = ms_text (v), *t = g_strdup_printf (_("for %s"), w);
      join (s, t);
      g_free (t);
      g_free (w);
    }
  if (*r->lane)
    {
      char *t = g_strdup_printf (_("lane %s"), r->lane);
      join (s, t);
      g_free (t);
    }
  if (js (j, "origin_request"))
    join (s, _("from another node"));
  set_subtitle (r->row, s->str);
  g_string_free (s, TRUE);

  /* the class drop-down: the lane's classes, this job's selected */
  JsonObject *lane = jo (lanes, r->lane);
  JsonObject *classes = jo (lane, "classes");
  GList *names = classes ? json_object_get_members (classes) : NULL;
  guint n = g_list_length (names), i = 0, selected = GTK_INVALID_LIST_POSITION;
  gboolean same = (n == g_list_model_get_n_items (G_LIST_MODEL (r->classes)));
  for (GList *l = names; same && l; l = l->next, i++)
    same = g_strcmp0 ((const char *) l->data, gtk_string_list_get_string (r->classes, i)) == 0;
  r->updating = TRUE;
  if (!same)
    {
      gtk_string_list_splice (r->classes, 0, g_list_model_get_n_items (G_LIST_MODEL (r->classes)), NULL);
      for (GList *l = names; l; l = l->next)
        gtk_string_list_append (r->classes, (const char *) l->data);
    }
  i = 0;
  for (GList *l = names; l; l = l->next, i++)
    if (g_strcmp0 ((const char *) l->data, cls) == 0)
      selected = i;
  if (selected == GTK_INVALID_LIST_POSITION && cls)
    {
      gtk_string_list_append (r->classes, cls);
      selected = n;
    }
  gtk_drop_down_set_selected (GTK_DROP_DOWN (r->drop), selected);
  r->updating = FALSE;
  g_list_free (names);
  gtk_widget_set_sensitive (r->drop, r->queued);
  gtk_widget_set_sensitive (r->cancel, TRUE);
}

static void
apply_jobs (GsmMaluosQueueView *self, JsonArray *queue, JsonObject *lanes)
{
  guint n = queue ? json_array_get_length (queue) : 0;
  gboolean same = (n == self->job_rows->len);
  for (guint i = 0; same && i < n; i++)
    same = g_strcmp0 (js (json_array_get_object_element (queue, i), "id"), ((JobRow *) g_ptr_array_index (self->job_rows, i))->id) == 0;
  if (!same)
    {
      for (guint i = 0; i < self->job_rows->len; i++)
        adw_preferences_group_remove (ADW_PREFERENCES_GROUP (self->queue_group), ((JobRow *) g_ptr_array_index (self->job_rows, i))->row);
      g_ptr_array_set_size (self->job_rows, 0);
      for (guint i = 0; i < n; i++)
        g_ptr_array_add (self->job_rows, job_row_new (self, json_array_get_object_element (queue, i)));
    }
  for (guint i = 0; i < n; i++)
    job_row_update ((JobRow *) g_ptr_array_index (self->job_rows, i), json_array_get_object_element (queue, i), lanes);
  gtk_widget_set_visible (self->empty_row, n == 0);
}

/* ---- the answers applied */

static void
apply_queue (GsmMaluosQueueView *self, JsonObject *reply, const char *error)
{
  GString *summary = g_string_new (NULL);
  gboolean ok = reply && jb (reply, "ok");

  gtk_widget_set_visible (self->note_row, !ok);
  if (!ok)
    {
      apply_lanes (self, NULL);
      apply_jobs (self, NULL, NULL);
      gtk_widget_set_visible (self->empty_row, FALSE);
      const char *code = reply ? js (reply, "error") : NULL;
      const char *msg = reply ? js (reply, "message") : NULL;
      if (error && strstr (error, "UnknownMethod"))
        {
          set_subtitle (self->note_row, _("The session service is older than this window: maluos-desktop-session 0.8.0 answers the queue."));
          g_string_append (summary, "no NodeQueue in the session service");
        }
      else if (error)
        {
          set_subtitle (self->note_row, error);
          g_string_append_printf (summary, "session error: %s", error);
        }
      else if (g_strcmp0 (code, "forbidden") == 0)
        {
          set_subtitle (self->note_row, _("Only an operator of the gateway sees every call. Your own calls are on the Desk's Models page."));
          g_string_append (summary, "forbidden (not an operator)");
        }
      else if (g_strcmp0 (code, "no_gateway") == 0)
        {
          set_subtitle (self->note_row, _("The inference gateway is not on this computer."));
          g_string_append (summary, "no gateway");
        }
      else
        {
          set_subtitle (self->note_row, msg ? msg : (code ? code : _("The queue could not be read.")));
          g_string_append_printf (summary, "%s", code ? code : "error");
        }
    }
  else
    {
      JsonObject *lanes = jo (reply, "lanes");
      JsonArray *queue = ja (reply, "queue");
      guint n = queue ? json_array_get_length (queue) : 0, running = 0;
      for (guint i = 0; i < n; i++)
        if (g_strcmp0 (js (json_array_get_object_element (queue, i), "state"), "running") == 0)
          running++;
      apply_lanes (self, lanes);
      apply_jobs (self, queue, lanes);
      GList *names = lanes ? json_object_get_members (lanes) : NULL;
      g_string_append_printf (summary, "%u jobs (%u running, %u queued) in %u lanes", n, running, n - running, g_list_length (names));
      g_list_free (names);
    }
  gsm_maluos_session_set_summary (self->session, "queue", summary->str);
  g_string_free (summary, TRUE);
}

static void
apply_state (GsmMaluosQueueView *self, JsonObject *root)
{
  JsonObject *gateway = jo (root, "gateway");
  JsonObject *queue = jo (gateway, "queue");
  JsonObject *office = jo (root, "office");
  double queued = 0, running = 0;

  if (gateway && jb (gateway, "available") && queue)
    {
      jd (queue, "queued", &queued);
      jd (queue, "running", &running);
      char *t = g_strdup_printf (_("Every call of every principal, live from the node API. The gateway counts %.0f queued and %.0f running."), queued, running);
      adw_preferences_group_set_description (ADW_PREFERENCES_GROUP (self->queue_group), t);
      g_free (t);
    }
  else
    adw_preferences_group_set_description (ADW_PREFERENCES_GROUP (self->queue_group), _("Every call of every principal, live from the node API."));

  g_clear_pointer (&self->office_url, g_free);
  if (office && jb (office, "enrolled") && js (office, "url"))
    {
      JsonObject *o = jo (office, "office");
      self->office_url = g_strdup (js (office, "url"));
      char *t = g_strdup_printf (_("History, usage by period, keys and policies live in %s's Sovereign LLM Manager (%s)."),
                                 o && js (o, "name") ? js (o, "name") : _("the office"), self->office_url);
      set_subtitle (self->manager_row, t);
      g_free (t);
      gtk_widget_set_sensitive (self->manager_row, TRUE);
    }
  else
    {
      set_subtitle (self->manager_row, _("Deep history, usage by period, keys and policies live in the office's Sovereign LLM Manager once this desk is enrolled."));
      gtk_widget_set_sensitive (self->manager_row, FALSE);
    }
}

static void
on_state (GsmMaluosSession *, JsonObject *state, gpointer data)
{
  apply_state ((GsmMaluosQueueView *) data, state);
}

static void
on_queue (GsmMaluosSession *, JsonObject *reply, const char *error, gpointer data)
{
  apply_queue ((GsmMaluosQueueView *) data, reply, error);
}

static void
on_manager_activated (AdwActionRow *, gpointer data)
{
  GsmMaluosQueueView *self = (GsmMaluosQueueView *) data;
  if (!self->office_url)
    return;
  GError *error = NULL;
  if (!g_app_info_launch_default_for_uri (self->office_url, NULL, &error))
    {
      toast (self, error ? error->message : _("cannot open the office"));
      g_clear_error (&error);
    }
}

void
maluos_queue_freeze (GsmMaluosQueueView *self)
{
  if (!self->watching)
    return;
  self->watching = FALSE;
  gsm_maluos_session_unwatch (self->session, (GsmMaluosWatch) (GSM_MALUOS_WATCH_STATE | GSM_MALUOS_WATCH_QUEUE));
}

void
maluos_queue_thaw (GsmMaluosQueueView *self)
{
  if (self->watching)
    return;
  self->watching = TRUE;
  gsm_maluos_session_watch (self->session, (GsmMaluosWatch) (GSM_MALUOS_WATCH_STATE | GSM_MALUOS_WATCH_QUEUE));
}

/* ---- GObject */

static void
gsm_maluos_queue_view_dispose (GObject *object)
{
  GsmMaluosQueueView *self = GSM_MALUOS_QUEUE_VIEW (object);

  maluos_queue_freeze (self);
  if (self->state_id)
    {
      g_signal_handler_disconnect (self->session, self->state_id);
      self->state_id = 0;
    }
  if (self->queue_id)
    {
      g_signal_handler_disconnect (self->session, self->queue_id);
      self->queue_id = 0;
    }
  if (self->lane_rows)
    {
      g_ptr_array_free (self->lane_rows, TRUE);
      self->lane_rows = NULL;
    }
  if (self->job_rows)
    {
      g_ptr_array_free (self->job_rows, TRUE);
      self->job_rows = NULL;
    }
  g_clear_pointer (&self->office_url, g_free);
  g_clear_pointer (&self->overlay, gtk_widget_unparent);

  G_OBJECT_CLASS (gsm_maluos_queue_view_parent_class)->dispose (object);
}

static void
gsm_maluos_queue_view_class_init (GsmMaluosQueueViewClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (klass);

  object_class->dispose = gsm_maluos_queue_view_dispose;
  gtk_widget_class_set_layout_manager_type (widget_class, GTK_TYPE_BIN_LAYOUT);
}

static void
gsm_maluos_queue_view_init (GsmMaluosQueueView *self)
{
  self->lane_rows = g_ptr_array_new_with_free_func (lane_row_free);
  self->job_rows = g_ptr_array_new_with_free_func (job_row_free);
  self->session = gsm_maluos_session_get ();

  self->overlay = adw_toast_overlay_new ();
  gtk_widget_set_parent (self->overlay, GTK_WIDGET (self));
  self->box = gtk_box_new (GTK_ORIENTATION_VERTICAL, 0);
  adw_toast_overlay_set_child (ADW_TOAST_OVERLAY (self->overlay), self->box);

  self->banner = adw_banner_new (_("The MaluOS session service is not answering"));
  g_object_bind_property (self->session, "stale", self->banner, "revealed", G_BINDING_SYNC_CREATE);
  gtk_box_append (GTK_BOX (self->box), self->banner);

  self->page = adw_preferences_page_new ();
  gtk_widget_set_vexpand (self->page, TRUE);
  gtk_box_append (GTK_BOX (self->box), self->page);

  self->lanes_group = adw_preferences_group_new ();
  adw_preferences_group_set_title (ADW_PREFERENCES_GROUP (self->lanes_group), _("Lanes"));
  adw_preferences_group_set_description (ADW_PREFERENCES_GROUP (self->lanes_group),
                                         _("Every backend of this computer's gateway is a lane with a capacity. A paused lane dispatches nothing."));
  adw_preferences_page_add (ADW_PREFERENCES_PAGE (self->page), ADW_PREFERENCES_GROUP (self->lanes_group));
  self->note_row = action_row (_("Nothing to show"), "—");
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->lanes_group), self->note_row);

  self->queue_group = adw_preferences_group_new ();
  adw_preferences_group_set_title (ADW_PREFERENCES_GROUP (self->queue_group), _("Queue"));
  adw_preferences_page_add (ADW_PREFERENCES_PAGE (self->page), ADW_PREFERENCES_GROUP (self->queue_group));
  self->empty_row = action_row (_("Nothing queued or running"), _("Calls appear here the moment the gateway admits them."));
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->queue_group), self->empty_row);

  self->more_group = adw_preferences_group_new ();
  adw_preferences_page_add (ADW_PREFERENCES_PAGE (self->page), ADW_PREFERENCES_GROUP (self->more_group));
  self->manager_row = action_row (_("Open in Sovereign LLM Manager"), "—");
  adw_action_row_set_activatable_widget (ADW_ACTION_ROW (self->manager_row), NULL);
  gtk_list_box_row_set_activatable (GTK_LIST_BOX_ROW (self->manager_row), TRUE);
  g_signal_connect (self->manager_row, "activated", G_CALLBACK (on_manager_activated), self);
  {
    GtkWidget *arrow = gtk_image_new_from_icon_name ("adw-external-link-symbolic");
    adw_action_row_add_suffix (ADW_ACTION_ROW (self->manager_row), arrow);
  }
  gtk_widget_set_sensitive (self->manager_row, FALSE);
  adw_preferences_group_add (ADW_PREFERENCES_GROUP (self->more_group), self->manager_row);

  self->state_id = g_signal_connect (self->session, "state", G_CALLBACK (on_state), self);
  self->queue_id = g_signal_connect (self->session, "queue", G_CALLBACK (on_queue), self);
  if (gsm_maluos_session_get_state (self->session))
    apply_state (self, gsm_maluos_session_get_state (self->session));
}

GsmMaluosQueueView *
gsm_maluos_queue_view_new (void)
{
  return GSM_MALUOS_QUEUE_VIEW (g_object_new (GSM_TYPE_MALUOS_QUEUE_VIEW, NULL));
}
