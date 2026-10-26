#ifndef _GSM_ARGV_H_
#define _GSM_ARGV_H_

#include <glibmm/optionentry.h>
#include <glibmm/optiongroup.h>
#include <glibmm/variantdict.h>
#include <vector>

namespace procman
{
class OptionGroup
  : public Glib::OptionGroup
{
private:
Glib::OptionEntry processes_tab_option;
Glib::OptionEntry resources_tab_option;
Glib::OptionEntry fs_tab_option;
Glib::OptionEntry show_version_option;
Glib::OptionEntry gpus_tab_option;          /* MaluOS */
Glib::OptionEntry network_tab_option;       /* MaluOS */
Glib::OptionEntry queue_tab_option;         /* MaluOS */
Glib::OptionEntry maluos_self_test_option;  /* MaluOS */
public:
OptionGroup();

bool show_system_tab;
bool show_processes_tab;
bool show_resources_tab;
bool show_file_systems_tab;
bool print_version;
bool show_gpus_tab;       /* MaluOS */
bool show_network_tab;    /* MaluOS */
bool show_queue_tab;      /* MaluOS */
bool maluos_self_test;    /* MaluOS */

std::vector<Glib::OptionEntry>  entries () const;
void                            load (const Glib::RefPtr<Glib::VariantDict> &args);
};
}

#endif /* _GSM_ARGV_H_ */
