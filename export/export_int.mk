#####################################################################################################
# register module
#####################################################################################################

units=export.mk
EXPORT_VER?=v1
$(call _register_module,export,EXPORT_VER,$(units))

#####################################################################################################
# export
#####################################################################################################

EXPORT_MOUNT_DIRS?=$(GCP_DSUB_ODIR_BUCKET_BASE)

# what to do on missing file (warning / error)
EXPORT_ON_MISSING_FILE?=warning

EXPORT_ID?=default
EXPORT_PREFIX?=export/$(PIPELINE_NAME)/$(PROJECT_NAME)/$(EXPORT_ID)
EXPORT_DIR?=/makeshift/$(EXPORT_PREFIX)

# by default export only contig table
EXPORT_VARIABLES?=CONTIG_TABLE

# user-defined evals these variables
EXPORT_VARIABLES_NOEVAL?=

# user-defined directories
EXPORT_USER_DIRS?=

EXPORT_TAG?=default

# this table keeps original file names, for local viewing
EXPORT_TABLE?=$(EXPORT_DIR)/table_$(EXPORT_TAG).txt

# same, for a set of exported variables
EXPORT_TABLE_SET?=$(EXPORT_DIR)/set_$(EXPORT_TAG).txt

# copy files, for export to other machine
# EXPORT_ODIR?=$(EXPORT_DIR)/$(EXPORT_ID)
# EXPORT_ODIR_TAR?=$(EXPORT_DIR)/$(EXPORT_ID).tar

