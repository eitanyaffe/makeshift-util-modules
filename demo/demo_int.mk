#####################################################################################################
# register module
#####################################################################################################

units=demo.mk
DEMO_VER?=v1.00
$(call _register_module,demo,DEMO_VER,$(units))

#####################################################################################################
# module basic definitions
#####################################################################################################

# include module version in directory
DEMO_DIR?=$(OUTPUT_DIR)/demo/$(DEMO_VER)

#####################################################################################################
# demo.mk parameters
#####################################################################################################

# subject id
DEMO_SID?=s1
DEMO_SUBJECT_DIR?=$(DEMO_DIR)/subjects/$(DEMO_SID)

# rule parameters
DEMO_SUBJECT_NAME?=Jane
DEMO_SUBJECT_HEIGHT?=160

# output per subject
DEMO_SUBJECT_TABLE?=$(DEMO_SUBJECT_DIR)/subject.txt

#####################################################################################################
# GCP directories
#####################################################################################################

# GCP work directory
DEMO_INFO_DIR?=$(DEMO_DIR)/info

# all run parametes are here
DEMO_SUBJECT_PARAM_TABLE?=$(INPUT_DIR)/params.txt
