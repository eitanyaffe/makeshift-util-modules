# copy figure files described in the manuscript json to the export directory
manuscript_export:
	$(call _start,$(MANUSCRIPT_EXPORT_DIR))
	python $(_md)/py/manuscript.py \
		ifn=$(MANUSCRIPT_JSON) \
		mount.dirs=$(MANUSCRIPT_MOUNT_DIRS) \
		on.missing.file=$(MANUSCRIPT_ON_MISSING_FILE) \
		odir=$(MANUSCRIPT_EXPORT_DIR) \
		$(call _export_variable,$(MANUSCRIPT_REFERENCED_VARS))
	cp $(MANUSCRIPT_JSON) $(MANUSCRIPT_EXPORT_DIR)/
	if [ -e $(MANUSCRIPT_LEGEND_MD) ]; then \
		cp $(MANUSCRIPT_LEGEND_MD) $(MANUSCRIPT_EXPORT_DIR)/; \
	fi
	$(_end)
