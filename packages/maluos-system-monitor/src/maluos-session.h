/* MaluOS: the session client shared by the MaluOS tabs (GPUs, MaluOS Network, Queue). See README.maluos.md.
 *
 * One object per process talks to com.maluos.Session on the session bus: GetState every two seconds while a
 * tab that renders the state is current (the GPUs and Network tabs), NodeQueue every two seconds while the
 * Queue tab is; each answer is emitted as a signal and every tab draws from it. The tabs hold no logic: every
 * number comes from the session service, and actions run maluctl. */
#ifndef _GSM_MALUOS_SESSION_H_
#define _GSM_MALUOS_SESSION_H_

#include <glib-object.h>
#include <json-glib/json-glib.h>

G_BEGIN_DECLS

#define GSM_TYPE_MALUOS_SESSION (gsm_maluos_session_get_type ())
G_DECLARE_FINAL_TYPE (GsmMaluosSession, gsm_maluos_session, GSM, MALUOS_SESSION, GObject)

typedef enum
{
  GSM_MALUOS_WATCH_STATE = 1 << 0,   /* GetState every two seconds: the GPUs and the Network tabs */
  GSM_MALUOS_WATCH_QUEUE = 1 << 1    /* NodeQueue every two seconds: the Queue tab */
} GsmMaluosWatch;

/* The one client of this process (created on first use; one GetState probe at creation decides whether the
 * tabs are shown).  Signals: "state" (JsonObject *state) after each GetState; "queue" (JsonObject *reply,
 * const char *error) after each NodeQueue, reply NULL when the call failed.  Properties: "available"
 * (the service has answered once: the tabs are shown), "stale" (a call failed after that: a banner). */
GsmMaluosSession *gsm_maluos_session_get (void);

void        gsm_maluos_session_watch         (GsmMaluosSession *self, GsmMaluosWatch what);
void        gsm_maluos_session_unwatch       (GsmMaluosSession *self, GsmMaluosWatch what);
void        gsm_maluos_session_update        (GsmMaluosSession *self);   /* now, whatever is watched */
gboolean    gsm_maluos_session_get_available (GsmMaluosSession *self);
JsonObject *gsm_maluos_session_get_state     (GsmMaluosSession *self);   /* the last state, or NULL; valid until the next "state" */

/* --maluos-self-test: GetState and NodeQueue once, print one line from the tabs' summaries, exit. */
void gsm_maluos_session_set_summary (GsmMaluosSession *self, const char *tab, const char *summary);
void gsm_maluos_session_self_test   (GsmMaluosSession *self);

/* Run a command (maluctl …) and hand its outcome back: ok and the last line of its output (stderr when it failed). */
typedef void (*GsmMaluosRunDone) (gboolean ok, const char *output, gpointer data);
void gsm_maluos_run (const char *const *argv, GsmMaluosRunDone done, gpointer data);

/* JSON helpers shared by the tabs: every missing or null member reads as "not there". */
JsonObject *gsm_maluos_jo (JsonObject *o, const char *name);
JsonArray  *gsm_maluos_ja (JsonObject *o, const char *name);
const char *gsm_maluos_js (JsonObject *o, const char *name);
gboolean    gsm_maluos_jd (JsonObject *o, const char *name, double *out);
gboolean    gsm_maluos_jb (JsonObject *o, const char *name);

G_END_DECLS

#endif /* _GSM_MALUOS_SESSION_H_ */
