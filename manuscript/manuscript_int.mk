####################################################################################################
# register module
####################################################################################################

units=manuscript.mk
MANUSCRIPT_VER?=v1
$(call _register_module,manuscript,MANUSCRIPT_VER,$(units))

####################################################################################################
# input
####################################################################################################

MANUSCRIPT_JSON?=$(_cd)/manuscript/figures.json

####################################################################################################
# export
####################################################################################################

MANUSCRIPT_MOUNT_DIRS?=$(EXPORT_MOUNT_DIRS)
MANUSCRIPT_ON_MISSING_FILE?=error

MANUSCRIPT_EXPORT_VER?=v1
MANUSCRIPT_EXPORT_DIR?=/makeshift/manuscripts/$(PIPELINE_NAME)/$(PROJECT_NAME)/$(MANUSCRIPT_EXPORT_VER)

# variable names referenced in the json (auto-extracted at parse time)
MANUSCRIPT_REFERENCED_VARS:=$(shell python $(_manuscript_path)/py/list_vars.py $(MANUSCRIPT_JSON) 2>/dev/null)
