#!/usr/bin/python3
# -*- coding: utf-8 -*-


import os
import shutil
from test_infra import utils


MyDir = "build/MyDir"


def installer_generate():

    utils.recreate_folder(MyDir, with_chmod=False, force_recreate=True)
    shutil.copy("files/install-config.yaml", MyDir)
    utils.run_command(f"build/openshift-install create manifests --dir={MyDir}")
    shutil.copy("files/install-config.yaml", MyDir)
    utils.run_command(f"build/openshift-install create ignition-configs --dir={MyDir}")
    return


def download_livecd(download_path, rhcos_version=None):
    rhcos_version = rhcos_version or os.getenv('RHCOS_VERSION', "46.82.202009222340-0")
    utils.run_command(f"curl {rhcos_version} --retry 5 -o {download_path}")


def embed(image_path, ignition_file):
    current_dir = os.getcwd()
    command = f"podman run --pull=always --privileged --rm -v /dev:/dev -v /run/udev:/run/udev " \
              f"-v {current_dir}/build:/data -w /data " \
              f"quay.io/coreos/coreos-installer:release iso ignition embed {image_path} -f --ignition-file " \
              f"/data/mydir/{ignition_file} -o /data/installer-SNO-image.iso"
    utils.run_command(command)
    shutil.copy("build/installer-SNO-image.iso", "/tmp/images")


if __name__ == "__main__":
    utils.extract_installer()
    installer_generate()
    download_livecd("build/installer-image.iso")
    embed("build/installer-image.iso", "build/bootstrap.ign")
