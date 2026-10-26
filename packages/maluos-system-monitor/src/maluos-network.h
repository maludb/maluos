/* MaluOS: the MaluOS Network tab (Phase 13 G5, the local half). See README.maluos.md.
 *
 * This node as the gateway's node API sees it (name, id, the listener, sharing, the manager, the lanes, the keys
 * issued), the nodes it is paired with by hand (remote backends) and the office; drawn from the session state's
 * `node` section (maluos-desktop-session 0.8.0). The estate's directory (slice D1) fills the rest later. */
#ifndef _GSM_MALUOS_NETWORK_H_
#define _GSM_MALUOS_NETWORK_H_

#include <gtk/gtk.h>

G_BEGIN_DECLS

#define GSM_TYPE_MALUOS_NETWORK_VIEW (gsm_maluos_network_view_get_type ())
G_DECLARE_FINAL_TYPE (GsmMaluosNetworkView, gsm_maluos_network_view, GSM, MALUOS_NETWORK_VIEW, GtkWidget)

GsmMaluosNetworkView *gsm_maluos_network_view_new (void);

void maluos_network_freeze (GsmMaluosNetworkView *self);
void maluos_network_thaw   (GsmMaluosNetworkView *self);

G_END_DECLS

#endif /* _GSM_MALUOS_NETWORK_H_ */
