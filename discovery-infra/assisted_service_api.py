# -*- coding: utf-8 -*-
import json
import os
import base64
import requests
import time

import consts
import utils
import shutil
import waiting
from assisted_service_client import ApiClient, Configuration, api, models
from logger import log


class InventoryClient(object):
    def __init__(self, inventory_url):
        self.inventory_url = inventory_url
        configs = Configuration()
        configs.host = self.inventory_url + "/api/assisted-install/v1"
        configs.verify_ssl = False
        self.set_config_auth(configs)

        self.api = ApiClient(configuration=configs)
        self.client = api.InstallerApi(api_client=self.api)

    def set_config_auth(self, c):
        offline_token = os.environ.get('OFFLINE_TOKEN', "")
        if offline_token == "":
            log.info("OFFLINE_TOKEN not set, skipping authentication headers")
            return

        def refresh_api_key(config):
            # Get the properly padded key segment
            auth = config.api_key.get('Authorization', None)
            if auth != None:
                segment = auth.split('.')[1]
                padding = len(segment) % 4
                segment = segment + padding * '='

                expires_on = json.loads(base64.b64decode(segment))['exp']

                # if this key doesn't expire or if it has more than 10 minutes left, don't refresh
                remaining = expires_on - time.time()
                if expires_on == 0 or remaining > 600:
                    return

            # fetch new key if expired or not set yet
            params = {
                "client_id":     "cloud-services",
                "grant_type":    "refresh_token",
                "refresh_token": offline_token,
            }

            log.info("Refreshing API key")
            response = requests.post(os.environ.get("SSO_URL"), data = params)
            response.raise_for_status()

            config.api_key['Authorization'] = response.json()['access_token']

        c.api_key_prefix['Authorization'] = 'Bearer'
        c.refresh_api_key_hook = refresh_api_key

    def wait_for_api_readiness(self):
        log.info("Waiting for inventory api to be ready")
        waiting.wait(
            lambda: self.clusters_list() is not None,
            timeout_seconds=consts.WAIT_FOR_BM_API,
            sleep_seconds=5,
            waiting_for="Wait till inventory is ready",
            expected_exceptions=Exception,
        )

    def create_cluster(self, name, ssh_public_key=None, **cluster_params):
        cluster = models.ClusterCreateParams(
            name=name, ssh_public_key=ssh_public_key, **cluster_params
        )
        log.info("Creating cluster with params %s", cluster.__dict__)
        result = self.client.register_cluster(new_cluster_params=cluster)
        return result

    def get_cluster_hosts(self, cluster_id):
        log.info("Getting registered nodes for cluster %s", cluster_id)
        return self.client.list_hosts(cluster_id=cluster_id)

    def get_hosts_in_statuses(self, cluster_id, statuses):
        hosts = self.get_cluster_hosts(cluster_id)
        return [hosts for host in hosts if host["status"] in statuses]

    def get_hosts_in_error_status(self, cluster_id):
        return self.get_hosts_in_statuses(cluster_id, [consts.NodesStatus.ERROR])

    def clusters_list(self):
        return self.client.list_clusters()

    def cluster_get(self, cluster_id):
        log.info("Getting cluster with id %s", cluster_id)
        return self.client.get_cluster(cluster_id=cluster_id)

    def _download(self, response, file_path):
        with open(file_path, "wb") as f:
            shutil.copyfileobj(response, f)

    def generate_image(self, cluster_id, ssh_key):
        log.info("Generating image for cluster %s", cluster_id)
        image_create_params = models.ImageCreateParams(ssh_public_key=ssh_key)
        log.info("Generating image with params %s", image_create_params.__dict__)
        return self.client.generate_cluster_iso(
            cluster_id=cluster_id, image_create_params=image_create_params
        )

    def download_image(self, cluster_id, image_path):
        log.info("Downloading image for cluster %s to %s", cluster_id, image_path)
        response = self.client.download_cluster_iso(
            cluster_id=cluster_id, _preload_content=False
        )
        self._download(response=response, file_path=image_path)

    def generate_and_download_image(self, cluster_id, ssh_key, image_path):
        self.generate_image(cluster_id=cluster_id, ssh_key=ssh_key)
        self.download_image(cluster_id=cluster_id, image_path=image_path)

    def set_hosts_roles(self, cluster_id, hosts_with_roles):
        log.info(
            "Setting roles for hosts %s in cluster %s", hosts_with_roles, cluster_id
        )
        hosts = models.ClusterUpdateParams(hosts_roles=hosts_with_roles)
        return self.client.update_cluster(
            cluster_id=cluster_id, cluster_update_params=hosts
        )

    def update_cluster(self, cluster_id, update_params):
        log.info("Updating cluster %s with params %s", cluster_id, update_params)
        return self.client.update_cluster(
            cluster_id=cluster_id, cluster_update_params=update_params
        )

    def delete_cluster(self, cluster_id):
        log.info("Deleting cluster %s", cluster_id)
        self.client.deregister_cluster(cluster_id=cluster_id)

    def get_hosts_id_with_macs(self, cluster_id):
        hosts = self.get_cluster_hosts(cluster_id)
        hosts_data = {}
        for host in hosts:
            inventory = json.loads(host.get("inventory", '{"interfaces":[]}'))
            hosts_data[host["id"]] = [
                interface["mac_address"] for interface in inventory["interfaces"]
            ]
        return hosts_data

    def get_host_by_mac(self, cluster_id, mac):
        hosts = self.get_cluster_hosts(cluster_id)

        for host in hosts:
            inventory = json.loads(host.get("inventory", '{"interfaces":[]}'))
            if mac.lower() in [
                interface["mac_address"].lower()
                for interface in inventory["interfaces"]
            ]:
                return host

    def download_and_save_file(self, cluster_id, file_name, file_path):
        log.info("Downloading %s to %s", file_name, file_path)
        response = self.client.download_cluster_files(
            cluster_id=cluster_id, file_name=file_name, _preload_content=False
        )
        with open(file_path, "wb") as _file:
            _file.write(response.data)

    def download_kubeconfig_no_ingress(self, cluster_id, kubeconfig_path):
        log.info("Downloading kubeconfig-noingress to %s", kubeconfig_path)
        self.download_and_save_file(
            cluster_id=cluster_id,
            file_name="kubeconfig-noingress",
            file_path=kubeconfig_path,
        )

    def download_kubeconfig(self, cluster_id, kubeconfig_path):
        log.info("Downloading kubeconfig to %s", kubeconfig_path)
        response = self.client.download_cluster_kubeconfig(
            cluster_id=cluster_id, _preload_content=False
        )
        with open(kubeconfig_path, "wb") as _file:
            _file.write(response.data)

    def install_cluster(self, cluster_id):
        log.info("Installing cluster %s", cluster_id)
        return self.client.install_cluster(cluster_id=cluster_id)

    def download_host_logs(self, cluster_id, host_id, output_file):
        log.info("Downloading logs to %s", output_file)
        try:
            response = self.client.download_host_logs(
                cluster_id=cluster_id, host_id=host_id, _preload_content=False
            )
            response.raise_for_status()
        except Exception:
            log.exception("Failed ot get logs for host %s", host_id)
            raise

        with open(output_file, "wb") as _file:
            _file.write(response.data)

    def download_logs_from_all_hosts(self, cluster_id, output_folder):
        hosts = self.get_cluster_hosts(cluster_id=cluster_id)
        for host in hosts:
            self.download_host_logs(cluster_id=cluster_id,
                                    host_id=host["id"],
                                    output_file=os.path.join(output_folder, f'{host["id"]}_logs.tar.gz'))


def create_client(url, wait_for_api=True):
    log.info('Creating assisted-service client for url: %s', url)
    c = InventoryClient(url)
    if wait_for_api:
        c.wait_for_api_readiness()
    return c
