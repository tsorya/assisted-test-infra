import json
import logging
from munch import Munch
from test_infra import utils
from test_infra import consts


DEFAULT_LOCK_FILE = "/tmp/network_pool.lock"


class NetworkAssets:

    def __init__(self, assets_file=consts.TF_NETWORK_POOL_PATH, lock_file=DEFAULT_LOCK_FILE):
        self.assets_file = assets_file
        self.lock_file = lock_file
        self._took_assets = []

    def get(self):
        logging.info("Taking asset from %s", self.assets_file)
        with utils.file_lock_context(self.lock_file):
            with open(self.assets_file) as _file:
                all_assets = json.load(_file)
            asset = Munch.fromDict(all_assets.pop(0))
            with open(self.assets_file, "w") as _file:
                json.dump(all_assets, _file)
            self._took_assets.append(asset)
        logging.info("Taken network asset: %s", asset)
        return asset

    def return_assets(self, assets):
        logging.info("Returning %d assets", len(assets))
        logging.debug("Assets to return: %s", assets)
        with utils.file_lock_context(self.lock_file):
            with open(self.assets_file) as _file:
                all_assets = json.load(_file)
            all_assets.extend([Munch.toDict(asset) for asset in assets])
            with open(self.assets_file, "w") as _file:
                json.dump(all_assets, _file)

    def release(self):
        logging.info("Returning all %d assets", len(self._took_assets))
        self.return_assets(self._took_assets)
