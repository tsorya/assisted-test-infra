import logging
import re
import yaml

import waiting

from typing import Optional, Union, Dict
from pprint import pformat

from kubernetes.client import ApiClient, CustomObjectsApi
from kubernetes.client.rest import ApiException

from tests.conftest import env_variables
from .base_resource import BaseCustomResource
from .cluster_deployment import ClusterDeployment
from .idict import IDict
from .secret import deploy_default_secret, Secret
from .global_vars import (
    CRD_API_GROUP,
    CRD_API_VERSION,
    DEFAULT_WAIT_FOR_CRD_STATUS_TIMEOUT,
    DEFAULT_WAIT_FOR_ISO_URL_TIMEOUT,
)


logger = logging.getLogger(__name__)


ISO_URL_PATTERN = re.compile(
    r"(?P<api_url>.+)/api/assisted-install/v1/clusters/" r"(?P<cluster_id>[0-9a-z-]+)/downloads/image"
)


class Proxy(IDict):
    """Proxy settings for the installation.

    Args:
        http_proxy (str): endpoint for accessing in every HTTP request.
        https_proxy (str): endpoint for accessing in every HTTPS request.
        no_proxy (str): comma separated values of addresses/address ranges/DNS entries
            that shouldn't be accessed via proxies.
    """

    def __init__(
        self,
        http_proxy: str,
        https_proxy: str,
        no_proxy: str,
    ):
        self.http_proxy = http_proxy
        self.https_proxy = https_proxy
        self.no_proxy = no_proxy

    def as_dict(self) -> dict:
        return {
            "httpProxy": self.http_proxy,
            "httpsProxy": self.https_proxy,
            "noProxy": self.no_proxy,
        }


class InfraEnv(BaseCustomResource):
    """
    InfraEnv is used to generate cluster iso.
    Image is automatically generated on CRD deployment, after InfraEnv is
    reconciled. Image download url will be exposed in the status.
    """

    _plural = "infraenvs"

    def __init__(
        self,
        kube_api_client: ApiClient,
        name: str,
        namespace: str = env_variables["namespace"],
    ):
        super().__init__(name, namespace)
        self.crd_api = CustomObjectsApi(kube_api_client)

    def create_from_yaml(self, yaml_data: dict) -> None:
        self.crd_api.create_namespaced_custom_object(
            group=CRD_API_GROUP,
            version=CRD_API_VERSION,
            plural=self._plural,
            body=yaml_data,
            namespace=self.ref.namespace,
        )

        logger.info("created infraEnv %s: %s", self.ref, pformat(yaml_data))

    def create(
        self,
        cluster_deployment: ClusterDeployment,
        secret: Secret,
        proxy: Optional[Proxy] = None,
        label_selector: Optional[Dict[str, str]] = None,
        ignition_config_override: Optional[str] = None,
        nmstate_label: Optional[str] = None,
        **kwargs,
    ) -> None:
        body = {
            "apiVersion": f"{CRD_API_GROUP}/{CRD_API_VERSION}",
            "kind": "InfraEnv",
            "metadata": self.ref.as_dict(),
            "spec": {
                "clusterRef": cluster_deployment.ref.as_dict(),
                "pullSecretRef": secret.ref.as_dict(),
                "nmStateConfigLabelSelector": {
                    "matchLabels": {f"{CRD_API_GROUP}/selector-nmstate-config-name": nmstate_label or ""}
                },
                "agentLabelSelector": {"matchLabels": label_selector or {}},
                "ignitionConfigOverride": ignition_config_override or "",
            },
        }
        spec = body["spec"]
        if proxy:
            spec["proxy"] = proxy.as_dict()
        spec.update(kwargs)
        self.crd_api.create_namespaced_custom_object(
            group=CRD_API_GROUP,
            version=CRD_API_VERSION,
            plural=self._plural,
            body=body,
            namespace=self.ref.namespace,
        )

        logger.info("created infraEnv %s: %s", self.ref, pformat(body))

    def patch(
        self,
        cluster_deployment: Optional[ClusterDeployment],
        secret: Optional[Secret],
        proxy: Optional[Proxy] = None,
        label_selector: Optional[Dict[str, str]] = None,
        ignition_config_override: Optional[str] = None,
        nmstate_label: Optional[str] = None,
        **kwargs,
    ) -> None:
        body = {"spec": kwargs}

        spec = body["spec"]
        if cluster_deployment:
            spec["clusterRef"] = cluster_deployment.ref.as_dict()

        if secret:
            spec["pullSecretRef"] = secret.ref.as_dict()

        if proxy:
            spec["proxy"] = proxy.as_dict()

        if label_selector:
            spec["agentLabelSelector"] = {"matchLabels": label_selector}

        if nmstate_label:
            spec["nmStateConfigLabelSelector"] = {
                "matchLabels": {
                    f"{CRD_API_GROUP}/selector-nmstate-config-name": nmstate_label,
                }
            }

        if ignition_config_override:
            spec["ignitionConfigOverride"] = ignition_config_override

        self.crd_api.patch_namespaced_custom_object(
            group=CRD_API_GROUP,
            version=CRD_API_VERSION,
            plural=self._plural,
            name=self.ref.name,
            namespace=self.ref.namespace,
            body=body,
        )

        logger.info("patching infraEnv %s: %s", self.ref, pformat(body))

    def get(self) -> dict:
        return self.crd_api.get_namespaced_custom_object(
            group=CRD_API_GROUP,
            version=CRD_API_VERSION,
            plural=self._plural,
            name=self.ref.name,
            namespace=self.ref.namespace,
        )

    def delete(self) -> None:
        self.crd_api.delete_namespaced_custom_object(
            group=CRD_API_GROUP,
            version=CRD_API_VERSION,
            plural=self._plural,
            name=self.ref.name,
            namespace=self.ref.namespace,
        )

        logger.info("deleted infraEnv %s", self.ref)

    def status(
        self,
        timeout: Union[int, float] = DEFAULT_WAIT_FOR_CRD_STATUS_TIMEOUT,
    ) -> dict:
        """
        Status is a section in the CRD that is created after registration to
        assisted service and it defines the observed state of InfraEnv.
        Since the status key is created only after resource is processed by the
        controller in the service, it might take a few seconds before appears.
        """

        def _attempt_to_get_status() -> dict:
            return self.get()["status"]

        return waiting.wait(
            _attempt_to_get_status,
            sleep_seconds=0.5,
            timeout_seconds=timeout,
            waiting_for=f"infraEnv {self.ref} status",
            expected_exceptions=KeyError,
        )

    def get_iso_download_url(
        self,
        timeout: Union[int, float] = DEFAULT_WAIT_FOR_ISO_URL_TIMEOUT,
    ):
        def _attempt_to_get_image_url() -> str:
            return self.get()["status"]["isoDownloadURL"]

        return waiting.wait(
            _attempt_to_get_image_url,
            sleep_seconds=3,
            timeout_seconds=timeout,
            waiting_for="image to be created",
            expected_exceptions=KeyError,
        )

    def get_cluster_id(self):
        iso_download_url = self.get_iso_download_url()
        return ISO_URL_PATTERN.match(iso_download_url).group("cluster_id")


def deploy_default_infraenv(
    kube_api_client: ApiClient,
    name: str,
    ignore_conflict: bool = True,
    cluster_deployment: Optional[ClusterDeployment] = None,
    secret: Optional[Secret] = None,
    proxy: Optional[Proxy] = None,
    label_selector: Optional[Dict[str, str]] = None,
    ignition_config_override: Optional[str] = None,
    **kwargs,
) -> InfraEnv:

    infra_env = InfraEnv(kube_api_client, name)
    try:
        if "filepath" in kwargs:
            _create_infraenv_from_yaml_file(
                infra_env=infra_env,
                filepath=kwargs["filepath"],
            )
        else:
            _create_infraenv_from_attrs(
                kube_api_client=kube_api_client,
                name=name,
                ignore_conflict=ignore_conflict,
                infra_env=infra_env,
                cluster_deployment=cluster_deployment,
                secret=secret,
                proxy=proxy,
                label_selector=label_selector,
                ignition_config_override=ignition_config_override,
                **kwargs,
            )
    except ApiException as e:
        if not (e.reason == "Conflict" and ignore_conflict):
            raise

    # wait until install-env will have status (i.e until resource will be
    # processed in assisted-service).
    infra_env.status()

    return infra_env


def _create_infraenv_from_yaml_file(
    infra_env: InfraEnv,
    filepath: str,
) -> None:
    with open(filepath) as fp:
        yaml_data = yaml.safe_load(fp)

    infra_env.create_from_yaml(yaml_data)


def _create_infraenv_from_attrs(
    kube_api_client: ApiClient,
    infra_env: InfraEnv,
    cluster_deployment: ClusterDeployment,
    secret: Optional[Secret] = None,
    proxy: Optional[Proxy] = None,
    label_selector: Optional[Dict[str, str]] = None,
    ignition_config_override: Optional[str] = None,
    **kwargs,
) -> None:
    if not secret:
        secret = deploy_default_secret(
            kube_api_client=kube_api_client,
            name=cluster_deployment.ref.name,
        )
    infra_env.create(
        cluster_deployment=cluster_deployment,
        secret=secret,
        proxy=proxy,
        label_selector=label_selector,
        ignition_config_override=ignition_config_override,
        **kwargs,
    )
