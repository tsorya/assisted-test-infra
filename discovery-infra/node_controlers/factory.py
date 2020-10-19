from node_controller import *


def factory():
    if os.environ.get('NODE_ENV') == 'QE_VM':
        return QeVmController()
    else:
        print("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
