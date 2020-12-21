import os
import shutil
import shlex
import logging
import yaml
from test_infra import utils, consts
from test_infra.controllers.node_controllers.terraform_controller import TerraformController

build = "build"
INSTALL_CONFIG_FILE_NAME = "install-config.yaml"
MY_DIR = f"{build}/mydir"
FILES = "discovery-infra/files"
INSTALL_CONFIG = os.path.join(MY_DIR, INSTALL_CONFIG_FILE_NAME)
INSTALL_COMMAND = "build/openshift-install"
EMBED_IMAGE_NAME = "installer-SNO-image.iso"


def installer_generate():
    logging.info("Installer generate manifests")
    utils.run_command(f"{INSTALL_COMMAND} create manifests --dir={MY_DIR}")
    logging.info("Installer generate ignitions")
    # TODO delete
    shutil.copy(f"{FILES}/sno_manifest.yaml", MY_DIR)
    utils.run_command(f"{INSTALL_COMMAND} create ignition-configs --dir={MY_DIR}")


def download_livecd(download_path, rhcos_version=None):
    logging.info("Downloading iso to %s", download_path)
    if os.path.exists(download_path):
        logging.info("Image %s already exists, skipping", download_path)

    rhcos_version = rhcos_version or os.getenv('RHCOS_VERSION', "46.82.202009222340-0")
    utils.run_command(f"curl https://releases-art-rhcos.svc.ci.openshift.org/art/storage/releases/rhcos-4.6/"
                      f"{rhcos_version}/x86_64/rhcos-{rhcos_version}-live.x86_64.iso --retry 5 -o {download_path}")


def embed(image_name, ignition_file, embed_image_name):
    logging.info("Embed ignition %s to iso %s", ignition_file, image_name)
    embedded_image = os.path.join(build, embed_image_name)
    os.remove(embedded_image) if os.path.exists(embedded_image) else None

    flags = shlex.split(f"--privileged --rm -v /dev:/dev -v /run/udev:/run/udev -v .:/data -w /data")
    utils.run_container("coreos-installer", "quay.io/coreos/coreos-installer:release", flags,
                        f"iso ignition embed {build}/{image_name} "
                        f"-f --ignition-file /data/{MY_DIR}/{ignition_file} -o /data/{embedded_image}")

    shutil.move(embedded_image, os.path.join(consts.BASE_IMAGE_FOLDER, embed_image_name))


def fill_install_config(pull_secret, ssh_pub_key):

    with open(INSTALL_CONFIG, "r") as _file:
        config = yaml.safe_load(_file)
    config["pullSecret"] = pull_secret
    config["sshKey"] = ssh_pub_key
    with open(INSTALL_CONFIG, "w") as _file:
        yaml.dump(config, _file)


def setup_files_and_folders(args):
    logging.info("Creating needed files and folders")
    utils.recreate_folder(consts.BASE_IMAGE_FOLDER, force_recreate=False)
    utils.recreate_folder(MY_DIR, with_chmod=False, force_recreate=True)
    shutil.copy(os.path.join(FILES, INSTALL_CONFIG_FILE_NAME), MY_DIR)
    fill_install_config(args.pull_secret, args.ssh_key)


def execute_ibip_flow(args):
    openshift_release_image = os.getenv('OPENSHIFT_INSTALL_RELEASE_IMAGE')
    if not openshift_release_image:
        raise Exception("os env OPENSHIFT_INSTALL_RELEASE_IMAGE must be provided")
    setup_files_and_folders(args)

    utils.extract_installer(openshift_release_image, build)

    installer_generate()
    download_livecd(f"{build}/installer-image.iso")
    embed("installer-image.iso", "bootstrap.ign", EMBED_IMAGE_NAME)
    # TODO TerraformController create and start nodes
