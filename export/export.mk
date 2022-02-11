
export_table:
	$(call _start,$(EXPORT_DIR))
	$(_R) R/export.r export.table \
		ofn=$(EXPORT_TABLE) \
		$(call _export_variable,$(EXPORT_VARIALBES)) \
		$(EXPORT_VARIALBES_NOEVAL)
	$(_end)

export_files:
	$(call _start,$(EXPORT_ODIR))
	$(_R) R/export.r export \
		odir=$(EXPORT_ODIR) \
		$(call _export_variable,$(EXPORT_VARIALBES)) \
		$(EXPORT_VARIALBES_NOEVAL)
ifneq ($(EXPORT_USER_DIRS),)
	cp -r $(EXPORT_USER_DIRS) $(EXPORT_ODIR)
endif
	tar cf $(EXPORT_ODIR_TAR) -C $(EXPORT_DIR) $(EXPORT_ID)
	$(_end)
