#####################################################################################################
# artifacts: the tables and files shipped alongside the manuscript
#
# each module in the methods registry declares what it ships in
# {module}/artifacts.json, grouped by instantiation path. make resolves each
# artifact variable with every dynamic key bound to its own name, which yields a
# path template the script instantiates from the group's table.
#####################################################################################################

_artifacts_py=python $(_md)/py/artifacts.py
_artifacts_json=$(ARTIFACTS_SRC_DIR)/$(ARTIFACTS_MODULE)/artifacts.json

# module:group pairs over every registered module that ships a json
_artifacts_pairs=$(shell $(_artifacts_py) groups \
	--ifn-methods $(MANUSCRIPT_METHODS_JSON) --src-dir $(ARTIFACTS_SRC_DIR))

# the active group, resolved when the group recipe expands
_artifacts_keys=$(shell $(_artifacts_py) keys --ifn $(_artifacts_json) --group $(ARTIFACTS_GROUP))
_artifacts_vars=$(shell $(_artifacts_py) vars --ifn $(_artifacts_json) --group $(ARTIFACTS_GROUP))
_artifacts_table_var=$(shell $(_artifacts_py) table --ifn $(_artifacts_json) --group $(ARTIFACTS_GROUP))

# binding each key to its own name turns the variable into a path template. a
# keyless group has a single concrete instance and needs no sub-make
_artifacts_binding=$(foreach k,$(_artifacts_keys),$k=$k)
_artifacts_templates=$(if $(_artifacts_keys),\
$(foreach v,$(_artifacts_vars),$v=$(call reval,$v,$(_artifacts_binding))),\
$(call _export_variable,$(_artifacts_vars)))

#####################################################################################################
# measure
#####################################################################################################

# one group of one module: resolve, instantiate, size, append to the work tables
artifacts_measure_group:
	$(call _assert,ARTIFACTS_MODULE ARTIFACTS_GROUP ARTIFACTS_ODIR)
	$(_artifacts_py) measure \
		--ifn $(_artifacts_json) \
		--group $(ARTIFACTS_GROUP) \
		--odir $(ARTIFACTS_ODIR) \
		--mount-dirs "$(ARTIFACTS_MOUNT_DIRS)" \
		--config-dir $(_cd) \
		--ifn-table "$($(_artifacts_table_var))" \
		--on-missing-file $(ARTIFACTS_ON_MISSING_FILE) \
		$(_artifacts_templates)

artifacts_measure:
	$(call _assert,ARTIFACTS_ODIR)
	$(_artifacts_py) init \
		--odir $(ARTIFACTS_ODIR) \
		--ifn-methods $(MANUSCRIPT_METHODS_JSON) \
		--src-dir $(ARTIFACTS_SRC_DIR)
	for pair in $(_artifacts_pairs); do \
		$(MAKE) artifacts_measure_group \
			ARTIFACTS_MODULE=$${pair%%:*} \
			ARTIFACTS_GROUP=$${pair##*:} \
			ARTIFACTS_ODIR=$(ARTIFACTS_ODIR) || exit 1; \
	done

#####################################################################################################
# scan and export
#####################################################################################################

# the audit pass: measure and report, copy nothing. this is where the size
# decisions are made, and it writes only under ARTIFACTS_SCAN_DIR
artifacts_scan:
	$(call _start,$(ARTIFACTS_SCAN_DIR))
	$(MAKE) artifacts_measure ARTIFACTS_ODIR=$(ARTIFACTS_SCAN_DIR)
	$(_artifacts_py) check \
		--odir $(ARTIFACTS_SCAN_DIR) \
		--max-group-gb $(ARTIFACTS_MAX_GROUP_GB) \
		--max-total-gb $(ARTIFACTS_MAX_TOTAL_GB)
	$(_end)

# the budget gate runs before the first byte is copied: a breach is one edit to
# fix beforehand and tens of gigabytes to undo afterwards
artifacts_export:
	$(call _start,$(ARTIFACTS_EXPORT_DIR))
	$(MAKE) artifacts_measure ARTIFACTS_ODIR=$(ARTIFACTS_EXPORT_DIR)
	$(_artifacts_py) check \
		--odir $(ARTIFACTS_EXPORT_DIR) \
		--max-group-gb $(ARTIFACTS_MAX_GROUP_GB) \
		--max-total-gb $(ARTIFACTS_MAX_TOTAL_GB) \
		--strict
	$(_artifacts_py) copy \
		--odir $(ARTIFACTS_EXPORT_DIR) \
		--on-missing-file $(ARTIFACTS_ON_MISSING_FILE)
	$(_artifacts_py) publish \
		--odir $(ARTIFACTS_EXPORT_DIR) \
		--pipeline $(PIPELINE_NAME) \
		--config $(PROJECT_NAME) \
		--tag $(ARTIFACTS_TAG)
	$(_end)

.PHONY: artifacts_scan artifacts_export artifacts_measure artifacts_measure_group
