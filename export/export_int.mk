#####################################################################################################
# register module
#####################################################################################################

units=export.mk
$(call _register_module,export,$(units),)

#####################################################################################################
# anchor export
#####################################################################################################

EXPORT_VER?=v1
EXPORT_ID?=default
EXPORT_DIR?=$(OUTPUT_DIR)/export/$(EXPORT_VER)/$(EXPORT_ID)

# by default export only contig table
EXPORT_VARIALBES?=CONTIG_TABLE

# user-defined evals these variables
EXPORT_VARIALBES_NOEVAL?=

# user-defined directories
EXPORT_USER_DIRS?=

# this table keeps original file names, for local viewing
EXPORT_TABLE?=$(EXPORT_DIR)/table

# copy files, for export to other machine
EXPORT_ODIR?=$(EXPORT_DIR)/$(EXPORT_ID)
EXPORT_ODIR_TAR?=$(EXPORT_DIR)/$(EXPORT_ID).tar

