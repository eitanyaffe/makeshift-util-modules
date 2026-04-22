#####################################################################################################
# register module
#####################################################################################################

units=index.mk
INDEX_VER?=specify_index
$(call _register_module,index,INDEX_VER,$(units))

#####################################################################################################
# index
#####################################################################################################

# mount base dir of the output bucket (local mount path)
INDEX_MOUNT_DIRS?=$(GCP_DSUB_ODIR_BUCKET_BASE)

# output GCS bucket (replaces mount dir in paths)
INDEX_OUTPUT_BUCKET?=$(GCP_DSUB_ODIR_BUCKET)

# what to do on missing file (warning / error)
INDEX_ON_MISSING_FILE?=error

# max items to index per grouping (0: all)
INDEX_MAX_ITEMS?=0

# modules to index (passed by pipeline)
INDEX_MODULES?=specify_module

# final export destination for combined indices, versioned independently of EXPORT_ID
INDEX_EXPORT_DIR?=/makeshift/export/$(PIPELINE_NAME)/$(PROJECT_NAME)/index/$(INDEX_VER)

# tag used to name per-grouping table files (set per call in {module}_index.mk)
INDEX_TAG?=default

# per-call: output table path
INDEX_TABLE?=$(INDEX_EXPORT_DIR)/table_$(INDEX_TAG).txt

# per-call: input table for index_set (table with dyn vars)
INDEX_TABLE_INPUT?=

# per-call: dynamic (row-driven) variable names
INDEX_DYN_VARIABLES?=

# per-call: variables to index
INDEX_VARIABLES?=

# per-call: json file mapping indexed variable name -> description
INDEX_DESCRIPTIONS?=
