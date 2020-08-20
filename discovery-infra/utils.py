# -*- coding: utf-8 -*-
import itertools
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import libvirt
import waiting
import requests
import consts
import oc_utils
from logger import log
from retry import retry
from pprint import pformat

conn = libvirt.open("qemu:///system")


def run_command(command, shell=False):
    command = command if shell else shlex.split(command)
    process = subprocess.run(
        command,
        shell=shell,
        check=True,
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )
    output = process.stdout.strip()
    return output


def run_command_with_output(command):
    with subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, bufsize=1, universal_newlines=True
    ) as p:
        for line in p.stdout:
            print(line, end="")  # process line here

    if p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, p.args)


def get_network_leases(network_name):
    net = conn.networkLookupByName(network_name)
    return net.DHCPLeases()


def wait_till_nodes_are_ready(nodes_count, network_name):
    log.info("Wait till %s nodes will be ready and have ips", nodes_count)
    try:
        waiting.wait(
            lambda: len(get_network_leases(network_name)) >= nodes_count,
            timeout_seconds=consts.NODES_REGISTERED_TIMEOUT * nodes_count,
            sleep_seconds=10,
            waiting_for="Nodes to have ips",
        )
        log.info("All nodes have booted and got ips")
    except:
        log.error(
            "Not all nodes are ready. Current dhcp leases are %s",
            get_network_leases(network_name),
        )
        raise


# Require wait_till_nodes_are_ready has finished and all nodes are up
def get_libvirt_nodes_mac_role_ip_and_name(network_name):
    nodes_data = {}
    try:
        leases = get_network_leases(network_name)
        for lease in leases:
            nodes_data[lease["mac"]] = {
                "ip": lease["ipaddr"],
                "name": lease["hostname"],
                "role": consts.NodeRoles.WORKER
                if consts.NodeRoles.WORKER in lease["hostname"]
                else consts.NodeRoles.MASTER,
            }
        return nodes_data
    except:
        log.error(
            "Failed to get nodes macs from libvirt. Output is %s",
            get_network_leases(network_name),
        )
        raise


def get_libvirt_nodes_macs(network_name):
    return get_libvirt_nodes_mac_role_ip_and_name(network_name).keys()


def are_all_libvirt_nodes_in_cluster_hosts(client, cluster_id, network_name):
    hosts_macs = client.get_hosts_id_with_macs(cluster_id)
    return all(
        mac.lower() in map(str.lower, itertools.chain(*hosts_macs.values()))
        for mac in get_libvirt_nodes_macs(network_name)
    )


def get_cluster_hosts_with_mac(client, cluster_id, macs):
    return [client.get_host_by_mac(cluster_id, mac) for mac in macs]


def get_tfvars():
    if not os.path.exists(consts.TFVARS_JSON_FILE):
        raise Exception("%s doesn't exists" % consts.TFVARS_JSON_FILE)
    with open(consts.TFVARS_JSON_FILE) as _file:
        tfvars = json.load(_file)
    return tfvars


def are_hosts_in_status(
        hosts, nodes_count, statuses, fall_on_error_status=True
):
    hosts_in_status = [host for host in hosts if host["status"] in statuses]
    if len(hosts_in_status) >= nodes_count:
        return True
    elif (
        fall_on_error_status
        and len([host for host in hosts if host["status"] == consts.NodesStatus.ERROR])
        > 0
    ):
        hosts_in_error = [
            host for host in hosts if host["status"] == consts.NodesStatus.ERROR
        ]
        log.error(
            "Some of the hosts are in insufficient or error status. Hosts in error %s",
            pformat(hosts_in_error),
        )
        raise Exception("All the nodes must be in valid status, but got some in error")

    log.info(
        "Asked hosts to be in one of the statuses from %s and currently hosts statuses are %s",
        statuses,
        [(host["id"], host["status"], host["status_info"]) for host in hosts],
    )
    return False


def wait_till_hosts_with_macs_are_in_status(
    client,
    cluster_id,
    macs,
    statuses,
    timeout=consts.NODES_REGISTERED_TIMEOUT,
    fall_on_error_status=True,
    interval=5,
):
    log.info("Wait till %s nodes are in one of the statuses %s", len(macs), statuses)

    try:
        waiting.wait(
            lambda: are_hosts_in_status(
                get_cluster_hosts_with_mac(client, cluster_id, macs),
                len(macs),
                statuses,
                fall_on_error_status,
            ),
            timeout_seconds=timeout,
            sleep_seconds=interval,
            waiting_for="Nodes to be in of the statuses %s" % statuses,
        )
    except:
        hosts = get_cluster_hosts_with_mac(client, cluster_id, macs)
        log.info("All nodes: %s", hosts)
        raise


def wait_till_all_hosts_are_in_status(
    client,
    cluster_id,
    nodes_count,
    statuses,
    timeout=consts.NODES_REGISTERED_TIMEOUT,
    fall_on_error_status=True,
    interval=5,
):
    hosts = client.get_cluster_hosts(cluster_id)
    log.info("Wait till %s nodes are in one of the statuses %s", nodes_count, statuses)

    try:
        waiting.wait(
            lambda: are_hosts_in_status(
                client.get_cluster_hosts(cluster_id),
                nodes_count,
                statuses,
                fall_on_error_status,
            ),
            timeout_seconds=timeout,
            sleep_seconds=interval,
            waiting_for="Nodes to be in of the statuses %s" % statuses,
        )
    except:
        hosts = client.get_cluster_hosts(cluster_id)
        log.info("All nodes: %s", hosts)
        raise


def wait_till_cluster_is_in_status(
    client, cluster_id, statuses, timeout=consts.NODES_REGISTERED_TIMEOUT, interval=30
):
    log.info("Wait till cluster %s is in status %s", cluster_id, statuses)
    try:
        waiting.wait(
            lambda: client.cluster_get(cluster_id).status in statuses,
            timeout_seconds=timeout,
            sleep_seconds=interval,
            waiting_for="Cluster to be in status %s" % statuses,
        )
    except:
        log.info("Cluster: %s", client.cluster_get(cluster_id))
        raise


def folder_exists(file_path):
    folder = Path(file_path).parent
    if not folder:
        log.warn("Directory %s doesn't exist. Please create it", folder)
        return False
    return True


def file_exists(file_path):
    return Path(file_path).exists()


def recreate_folder(folder):
    if os.path.exists(folder):
        shutil.rmtree(folder)
    os.makedirs(folder, exist_ok=True)
    run_command("chmod ugo+rx %s" % folder)


def get_assisted_service_url_by_args(args, wait=True):
    if hasattr(args, 'inventory_url') and args.inventory_url:
        return args.inventory_url

    kwargs = {
        'service': args.service_name,
        'namespace': args.namespace
    }
    if args.oc_mode:
        get_url = get_remote_assisted_service_url
        kwargs['oc'] = oc_utils.OC(token=args.oc_token, server=args.oc_server)
        kwargs['scheme'] = args.oc_scheme
    else:
        get_url = get_local_assisted_service_url

    return retry(
        tries=5 if wait else 1,
        delay=3,
        backoff=2,
        exceptions=(
            requests.ConnectionError,
            requests.ConnectTimeout,
            requests.RequestException
        )
    )(get_url)(**kwargs)


def get_remote_assisted_service_url(oc, namespace, service, scheme):
    log.info('Getting oc %s URL in %s namespace', service, namespace)
    service_urls = oc_utils.get_namespaced_service_urls_list(
        oc=oc,
        namespace=namespace,
        service=service,
        scheme=scheme
    )
    for url in service_urls:
        if is_assisted_service_reachable(url):
            return url

    raise RuntimeError(
        f'could not find any reachable url to {service} service '
        f'in {namespace} namespace'
    )


def get_local_assisted_service_url(namespace, service):
    log.info('Getting minikube %s URL in %s namespace', service, namespace)
    url = run_command(f'minikube -n {namespace} service {service} --url')
    if is_assisted_service_reachable(url):
        return url

    raise RuntimeError(
        f'could not find any reachable url to {service} service '
        f'in {namespace} namespace'
    )


def is_assisted_service_reachable(url):
    r = requests.get(url + '/health', timeout=10)
    return r.status_code == 200
