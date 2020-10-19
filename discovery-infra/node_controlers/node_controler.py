import os
from typing import Dict


class NodeControler:

    @staticmethod
    def factory():
        if os.environ.get('NODE_ENV') == 'QE_VM':
            return
        #return eval(type + "()")
        if type == "Circle": return Circle()
        if type == "Square": return Square()
        assert 0, "Bad shape creation: " + type
    factory = staticmethod(factory)

    def list_nodes(self) -> Dict[str, str]:
        raise NotImplementedError

    def shutdown_node(self, node_name: str) -> None:
        raise NotImplementedError

    def shutdown_all_nodes(self) -> None:
        raise NotImplementedError

    def start_node(self, node_name: str) -> None:
        raise NotImplementedError

    def start_all_nodes(self) -> None:
        raise NotImplementedError

    def restart_node(self, node_name: str) -> None:
        raise NotImplementedError

    def format_node_disk(self, node_name: str) -> None:
        raise NotImplementedError

    def format_all_node_disks(self, node_name: str) -> None:
        raise NotImplementedError

    def get_ingress_and_api_vips(self) -> dict:
        raise NotImplementedError
