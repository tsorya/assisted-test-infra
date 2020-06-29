
BMI_BRANCH := $(or $(BMI_BRANCH), "master")
IMAGE := $(or $(IMAGE), "")
NUM_MASTERS :=  $(or $(NUM_MASTERS),3)
WORKER_MEMORY ?= 8892
MASTER_MEMORY ?= 16984
NUM_WORKERS := $(or $(NUM_WORKERS),0)
STORAGE_POOL_PATH := $(or $(STORAGE_POOL_PATH), $(PWD)/storage_pool)
SSH_PUB_KEY := $(or $(SSH_PUB_KEY),$(shell cat ssh_key/key.pub))
PULL_SECRET :=  $(or $(PULL_SECRET), $(shell if ! [ -z "${PULL_SECRET_FILE}" ];then cat ${PULL_SECRET_FILE};fi))
SHELL=/bin/sh
CONTAINER_COMMAND = $(shell if [ -x "$(shell command -v docker)" ];then echo "docker" ; else echo "podman";fi)
CLUSTER_NAME := $(or $(CLUSTER_NAME),test-infra-cluster)
BASE_DOMAIN := $(or $(BASE_DOMAIN),redhat.com)
NETWORK_CIDR := $(or $(NETWORK_CIDR),"192.168.126.0/24")
CLUSTER_ID := $(or $(CLUSTER_ID), "")
IMAGE_TAG := latest
DEPLOY_TAG := $(or $(DEPLOY_TAG), "")
IMAGE_NAME=test-infra
IMAGE_REG_NAME=quay.io/itsoiref/$(IMAGE_NAME)
NETWORK_NAME := $(or $(NETWORK_NAME), test-infra-net)
NETWORK_BRIDGE := $(or $(NETWORK_BRIDGE), tt0)
OPENSHIFT_VERSION := $(or $(OPENSHIFT_VERSION), 4.5)
PROXY_URL := $(or $(PROXY_URL), "")
RUN_WITH_VIPS := $(or $(RUN_WITH_VIPS), "yes")
SKIPPER_PARAMS ?= -i
REMOTE_INVENTORY_URL := $(or $(REMOTE_INVENTORY_URL), "")

.EXPORT_ALL_VARIABLES:


.PHONY: image_build run destroy start_minikube delete_minikube run destroy install_minikube deploy_bm_inventory create_environment delete_all_virsh_resources _download_iso _deploy_bm_inventory _deploy_nodes  _destroy_terraform

###########
# General #
###########

all:
	./install_env_and_run_full_flow.sh

destroy: destroy_nodes delete_minikube
	rm -rf build/terraform/*

###############
# Environment #
###############

create_full_environment:
	./create_full_environment.sh

create_environment: image_build bring_bm_inventory start_minikube

image_build:
	$(CONTAINER_COMMAND) pull $(IMAGE_REG_NAME):$(IMAGE_TAG) && $(CONTAINER_COMMAND) image tag $(IMAGE_REG_NAME):$(IMAGE_TAG) $(IMAGE_NAME):$(IMAGE_TAG) || $(CONTAINER_COMMAND) build -t $(IMAGE_NAME) -f Dockerfile.test-infra .

clean:
	rm -rf build
	rm -rf bm-inventory

############
# Minikube #
############

install_minikube:
	scripts/install_minikube.sh

start_minikube:
	scripts/run_minikube.sh
	eval $(minikube docker-env)

delete_minikube:
	minikube delete
	skipper run discovery-infra/virsh_cleanup.py -m

#############
# Terraform #
#############

copy_terraform_files:
	mkdir -p build/terraform
	FILE=build/terraform/terraform.tfvars.json
	cp -r terraform_files/* build/terraform/;\

run_terraform_from_skipper:
		cd build/terraform/ && terraform init  -plugin-dir=/root/.terraform.d/plugins/ && terraform apply -auto-approve -input=false -state=terraform.tfstate -state-out=terraform.tfstate -var-file=terraform.tfvars.json

run_terraform: copy_terraform_files
	skipper make run_terraform_from_skipper $(SKIPPER_PARAMS)

_destroy_terraform:
	cd build/terraform/  && terraform destroy -auto-approve -input=false -state=terraform.tfstate -state-out=terraform.tfstate -var-file=terraform.tfvars.json || echo "Failed cleanup terraform"
	discovery-infra/virsh_cleanup.py -f test-infra

destroy_terraform:
	skipper make _destroy_terraform $(SKIPPER_PARAMS)

#######
# Run #
#######

run: deploy_bm_inventory deploy_ui

run_full_flow: run deploy_nodes set_dns

redeploy_all: destroy run_full_flow

run_full_flow_with_install: run deploy_nodes_with_install set_dns

redeploy_all_with_install: destroy  run_full_flow_with_install

set_dns:
	scripts/assisted_deployment.sh	set_dns

deploy_ui: start_minikube
	DEPLOY_TAG=$(DEPLOY_TAG) scripts/deploy_ui.sh

kill_all_port_forwardings:
	scripts/utils.sh kill_all_port_forwardings

###########
# Cluster #
###########

_install_cluster:
	discovery-infra/install_cluster.py -id $(CLUSTER_ID) -ps '$(PULL_SECRET)'

install_cluster:
	skipper make _install_cluster $(SKIPPER_PARAMS)


#########
# Nodes #
#########

_deploy_nodes:
	discovery-infra/start_discovery.py -i $(IMAGE) -n $(NUM_MASTERS) -p $(STORAGE_POOL_PATH) -k '$(SSH_PUB_KEY)' -mm $(MASTER_MEMORY) -wm $(WORKER_MEMORY) -nw $(NUM_WORKERS) -ps '$(PULL_SECRET)' -bd $(BASE_DOMAIN) -cN $(CLUSTER_NAME) -vN $(NETWORK_CIDR) -nN $(NETWORK_NAME) -nB $(NETWORK_BRIDGE) -ov $(OPENSHIFT_VERSION) -rv $(RUN_WITH_VIPS) -iU $(REMOTE_INVENTORY_URL) -id $(CLUSTER_ID) $(ADDITIONAL_PARAMS)

deploy_nodes_with_install:
	skipper make _deploy_nodes ADDITIONAL_PARAMS=-in $(SKIPPER_PARAMS)

deploy_nodes:
	skipper make _deploy_nodes $(SKIPPER_PARAMS)

destroy_nodes:
	skipper run 'discovery-infra/delete_nodes.py -iU $(REMOTE_INVENTORY_URL) -id $(CLUSTER_ID)' $(SKIPPER_PARAMS)

redeploy_nodes: destroy_nodes deploy_nodes

redeploy_nodes_with_install: destroy_nodes deploy_nodes_with_install

#############
# Inventory #
#############

deploy_bm_inventory: start_minikube bring_bm_inventory
	mkdir -p bm-inventory/build
	DEPLOY_TAG=$(DEPLOY_TAG) scripts/deploy_bm_inventory.sh

bring_bm_inventory:
	@if cd bm-inventory; then git fetch --all && git reset --hard origin/$(BMI_BRANCH); else git clone --branch $(BMI_BRANCH) https://github.com/filanov/bm-inventory;fi

clear_inventory:
	make -C bm-inventory/ clear-deployment

delete_all_virsh_resources: destroy_nodes delete_minikube
	skipper run 'discovery-infra/delete_nodes.py -a' $(SKIPPER_PARAMS)

build_and_push_image:
	$(CONTAINER_COMMAND) build -t $(IMAGE_NAME):$(IMAGE_TAG) -f Dockerfile.test-infra .
	$(CONTAINER_COMMAND) tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_REG_NAME):$(IMAGE_TAG)
	$(CONTAINER_COMMAND) push $(IMAGE_REG_NAME):$(IMAGE_TAG)

#######
# ISO #
#######

_download_iso:
	discovery-infra/start_discovery.py -k '$(SSH_PUB_KEY)'  -ps '$(PULL_SECRET)' -bd $(BASE_DOMAIN) -cN $(CLUSTER_NAME) -ov $(OPENSHIFT_VERSION) -pU $(PROXY_URL) -iU $(REMOTE_INVENTORY_URL) -id $(CLUSTER_ID) -iO

download_iso:
	skipper make _download_iso $(SKIPPER_PARAMS)

download_iso_for_remote_use: deploy_bm_inventory
	skipper make _download_iso $(SKIPPER_PARAMS)

########
# Test #
########

lint:
	skipper make _lint

_lint:
	pre-commit run --all-files
