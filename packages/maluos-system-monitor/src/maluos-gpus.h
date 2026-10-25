/* MaluOS: the GPUs tab (Phase 13, shared GPUs, slice G1; docs/phase13-shared-gpus.md).
 *
 * A view that renders what the MaluOS desktop session publishes (com.maluos.Session GetState):
 * this computer's GPUs, the sharing switch, the loaded models and the queue, the office. It
 * computes nothing: every number comes from maluos_gpu.py and the gateway through the session,
 * and the one action (the sharing switch) runs `pkexec maluctl gateway share`.
 */
#pragma once

#include <gtk/gtk.h>

G_BEGIN_DECLS

#define GSM_TYPE_MALUOS_GPUS_VIEW (gsm_maluos_gpus_view_get_type ())

G_DECLARE_FINAL_TYPE (GsmMaluosGpusView, gsm_maluos_gpus_view, GSM, MALUOS_GPUS_VIEW, GtkWidget)

GsmMaluosGpusView *gsm_maluos_gpus_view_new (void);

/* TRUE once the session service has answered; the tab is shown when it is */
gboolean gsm_maluos_gpus_view_get_available (GsmMaluosGpusView *self);

void maluos_gpus_update (GsmMaluosGpusView *self);
void maluos_gpus_freeze (GsmMaluosGpusView *self);
void maluos_gpus_thaw (GsmMaluosGpusView *self);

/* --maluos-self-test: after the first answer (or 20 s) print one line and exit 0, or 1 when the session never answered */
void gsm_maluos_gpus_view_self_test (GsmMaluosGpusView *self);

G_END_DECLS
