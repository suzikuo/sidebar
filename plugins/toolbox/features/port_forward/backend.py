import subprocess
from typing import Dict, List


def get_proxies() -> List[Dict[str, str]]:
    """
    Get a list of all current port forward rules.
    Returns a list of dicts: [{'listen_address', 'listen_port', 'connect_address', 'connect_port'}, ...]
    """
    try:
        result = subprocess.run(
            ["netsh", "interface", "portproxy", "show", "all"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = result.stdout

        rules = []
        for line in output.splitlines():
            line = line.strip()
            # Match: IP (or *) port IP (or name) port
            tokens = line.split()
            if len(tokens) == 4 and tokens[1].isdigit() and tokens[3].isdigit():
                rules.append(
                    {
                        "listen_address": tokens[0],
                        "listen_port": tokens[1],
                        "connect_address": tokens[2],
                        "connect_port": tokens[3],
                    }
                )
        return rules
    except Exception as e:
        print(f"Error getting proxies: {e}")
        return []


def add_proxy(
    listen_address: str, listen_port: str, connect_address: str, connect_port: str
) -> bool:
    """
    Add or update a port proxy. Requires Admin privileges.
    """
    cmd = (
        f"Start-Process -FilePath 'netsh' "
        f"-ArgumentList 'interface portproxy add v4tov4 listenport={listen_port} listenaddress={listen_address} connectport={connect_port} connectaddress={connect_address}' "
        f"-Verb RunAs -Wait -WindowStyle Hidden"
    )
    try:
        subprocess.run(
            ["powershell", "-Command", cmd], creationflags=subprocess.CREATE_NO_WINDOW
        )
        return True
    except Exception as e:
        print(f"Error adding proxy: {e}")
        return False


def delete_proxy(listen_address: str, listen_port: str) -> bool:
    """
    Delete a port proxy. Requires Admin privileges.
    """
    cmd = (
        f"Start-Process -FilePath 'netsh' "
        f"-ArgumentList 'interface portproxy delete v4tov4 listenport={listen_port} listenaddress={listen_address}' "
        f"-Verb RunAs -Wait -WindowStyle Hidden"
    )
    try:
        subprocess.run(
            ["powershell", "-Command", cmd], creationflags=subprocess.CREATE_NO_WINDOW
        )
        return True
    except Exception as e:
        print(f"Error deleting proxy: {e}")
        return False
