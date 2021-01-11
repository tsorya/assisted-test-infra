import socket
import logging


def is_open(ip, port, timeout=5):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, int(port)))
        s.shutdown(socket.SHUT_RDWR)
        logging.info("Ip %s with port %s are reachable", ip, port)
        return True
    except:
        logging.info("Ip %s with port %s are not reachable", ip, port)
        return False
    finally:
        s.close()
