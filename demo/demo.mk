####################################################################################
# rule for single subject
####################################################################################

DEMO_SUBJECT_DONE?=$(DEMO_SUBJECT_DIR)/.done_subject
$(DEMO_SUBJECT_DONE):
	$(call _start,$(DEMO_SUBJECT_DIR))
	echo "$(DEMO_SUBJECT_NAME) is $(DEMO_SUBJECT_HEIGHT)cm" > $(DEMO_SUBJECT_TABLE)
	echo `nproc` >> $(DEMO_SUBJECT_TABLE)
	echo $$(($$(getconf _PHYS_PAGES) * $$(getconf PAGE_SIZE) / (1024 * 1024))) >> $(DEMO_SUBJECT_TABLE)
	$(_end_touch)
demo_subject: $(DEMO_SUBJECT_DONE)

####################################################################################
# rule for all subjects
####################################################################################

DEMO_ALL_DONE?=$(DEMO_INFO_DIR)/.done
$(DEMO_ALL_DONE):
	$(call _start,$(DEMO_INFO_DIR))
	$(MAKE) m=par par_tasks_complex \
		PAR_MODULE=demo \
		PAR_NAME=demo_task \
		PAR_WORK_DIR=$(DEMO_INFO_DIR) \
		PAR_TARGET=demo_subject \
		PAR_TASK_DIR=$(DEMO_SUBJECT_DIR) \
		PAR_TASK_ITEM_TABLE=$(DEMO_SUBJECT_PARAM_TABLE) \
		PAR_TASK_ITEM_VAR=DEMO_SID \
		PAR_TASK_ODIR_VAR=DEMO_SUBJECT_DIR \
		PAR_MAKEFLAGS="$(PAR_MAKEOVERRIDES)"
	$(_end_touch)
demo_subjects: $(DEMO_ALL_DONE)
