#include <config.h>

#include <glib/gi18n.h>
#include <glibmm/optionentry.h>

#include "argv.h"

namespace procman
{
OptionGroup::OptionGroup()
  : Glib::OptionGroup ("", ""),
  show_system_tab (false),
  show_processes_tab (false),
  show_resources_tab (false),
  show_file_systems_tab (false),
  print_version (false),
  show_gpus_tab (false),
  maluos_self_test (false)
{
  processes_tab_option.set_long_name ("show-processes-tab");
  processes_tab_option.set_short_name ('p');
  processes_tab_option.set_description (_("Show the Processes tab"));

  resources_tab_option.set_long_name ("show-resources-tab");
  resources_tab_option.set_short_name ('r');
  resources_tab_option.set_description (_("Show the Resources tab"));

  fs_tab_option.set_long_name ("show-file-systems-tab");
  fs_tab_option.set_short_name ('f');
  fs_tab_option.set_description (_("Show the File Systems tab"));

  show_version_option.set_long_name ("version");
  show_version_option.set_description (_("Show the application’s version"));

  /* MaluOS */
  gpus_tab_option.set_long_name ("show-gpus-tab");
  gpus_tab_option.set_short_name ('g');
  gpus_tab_option.set_description (_("Show the GPUs tab"));
  maluos_self_test_option.set_long_name ("maluos-self-test");
  maluos_self_test_option.set_description (_("Build the window, read the MaluOS session state once, print a summary and exit"));

  this->add_entry (processes_tab_option, this->show_processes_tab);
  this->add_entry (resources_tab_option, this->show_resources_tab);
  this->add_entry (fs_tab_option, this->show_file_systems_tab);
  this->add_entry (show_version_option, this->print_version);
  this->add_entry (gpus_tab_option, this->show_gpus_tab);
  this->add_entry (maluos_self_test_option, this->maluos_self_test);
}

std::vector<Glib::OptionEntry> OptionGroup::entries() const {
  return std::vector<Glib::OptionEntry> {
    processes_tab_option,
    resources_tab_option,
    fs_tab_option,
    show_version_option,
    gpus_tab_option,
    maluos_self_test_option
  };
}

void OptionGroup::load(const Glib::RefPtr<Glib::VariantDict> &args) {
  show_processes_tab = args->contains (processes_tab_option.get_long_name () );
  show_resources_tab = args->contains (resources_tab_option.get_long_name () );
  show_file_systems_tab = args->contains (fs_tab_option.get_long_name () );
  print_version = args->contains (show_version_option.get_long_name () );
  show_gpus_tab = args->contains (gpus_tab_option.get_long_name () );
  maluos_self_test = args->contains (maluos_self_test_option.get_long_name () );
}
}
