/* MaluOS: the GPUs tab (Phase 13 G1). See README.maluos.md.
 *
 * A GtkWidget that renders this computer's GPUs, the sharing switch, the models loaded and the queue from the
 * MaluOS session service's state (maluos-session.h), which it watches while its tab is current; the switch
 * runs `pkexec maluctl gateway share on|off`. */
#ifndef _GSM_MALUOS_GPUS_H_
#define _GSM_MALUOS_GPUS_H_

#include <gtk/gtk.h>

G_BEGIN_DECLS

#define GSM_TYPE_MALUOS_GPUS_VIEW (gsm_maluos_gpus_view_get_type ())
G_DECLARE_FINAL_TYPE (GsmMaluosGpusView, gsm_maluos_gpus_view, GSM, MALUOS_GPUS_VIEW, GtkWidget)

GsmMaluosGpusView *gsm_maluos_gpus_view_new (void);

void maluos_gpus_freeze (GsmMaluosGpusView *self);   /* the tab is no longer current */
void maluos_gpus_thaw   (GsmMaluosGpusView *self);   /* the tab is current: follow the state */

G_END_DECLS

#endif /* _GSM_MALUOS_GPUS_H_ */
