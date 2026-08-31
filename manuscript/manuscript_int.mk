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

# methods templates live with the pipeline that ran the steps they describe,
# not with the module: one directory holds the paper's whole methods coverage.
# per module: {module}/{module}.md and dry/$(PROJECT_NAME)/
MANUSCRIPT_METHODS_SRC_DIR?=$(PIPELINE_DIR)/methods

####################################################################################################
# export
####################################################################################################

MANUSCRIPT_MOUNT_DIRS?=$(EXPORT_MOUNT_DIRS)
MANUSCRIPT_ON_MISSING_FILE?=error

# everything a manuscript generates lives under here, outside the bucket and
# gitignored: these are derived files, regenerated on demand
MANUSCRIPT_BASE_DIR?=/makeshift/manuscripts/$(PIPELINE_NAME)/$(PROJECT_NAME)

MANUSCRIPT_EXPORT_VER?=v1
MANUSCRIPT_EXPORT_DIR?=$(MANUSCRIPT_BASE_DIR)/$(MANUSCRIPT_EXPORT_VER)

# where each module compiles its methods docs. deliberately outside the
# versioned export dir: a module must not need to know MANUSCRIPT_EXPORT_VER,
# so it writes a stable current copy here and the export snapshots it.
MANUSCRIPT_METHODS_DIR?=$(MANUSCRIPT_BASE_DIR)/methods

# variable names referenced in the json (auto-extracted at parse time)
MANUSCRIPT_REFERENCED_VARS:=$(shell python $(_manuscript_path)/py/list_vars.py $(MANUSCRIPT_JSON) 2>/dev/null)
