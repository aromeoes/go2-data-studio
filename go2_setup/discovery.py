import json
from unitree_webrtc_connect.multicast_scanner import discover_ip_sn


if __name__ == "__main__":
    print(json.dumps(discover_ip_sn(timeout=1)))
