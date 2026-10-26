/* MaluOS: the Queue tab (Phase 13 G5, the local half). See README.maluos.md.
 *
 * This computer's gateway queue as its node API serves it: every lane (pause, resume) and every queued or
 * running call of every principal (cancel, move to another class), read live through the session service's
 * NodeQueue every two seconds while the tab is current; the actions run `maluctl gateway node …`. The estate's
 * queues (slice D2) and the deep history (the Sovereign LLM Manager) are not here. */
#ifndef _GSM_MALUOS_QUEUE_H_
#define _GSM_MALUOS_QUEUE_H_

#include <gtk/gtk.h>

G_BEGIN_DECLS

#define GSM_TYPE_MALUOS_QUEUE_VIEW (gsm_maluos_queue_view_get_type ())
G_DECLARE_FINAL_TYPE (GsmMaluosQueueView, gsm_maluos_queue_view, GSM, MALUOS_QUEUE_VIEW, GtkWidget)

GsmMaluosQueueView *gsm_maluos_queue_view_new (void);

void maluos_queue_freeze (GsmMaluosQueueView *self);
void maluos_queue_thaw   (GsmMaluosQueueView *self);

G_END_DECLS

#endif /* _GSM_MALUOS_QUEUE_H_ */
