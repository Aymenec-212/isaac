"""Fail closed on unsafe deployment inputs; reads ARM parameter JSON only."""

import argparse
import ipaddress
import json
import re
from pathlib import Path


def validate(params):
    values = {name: entry["value"] for name, entry in params["parameters"].items()}
    network = ipaddress.ip_network(values["operatorCidr"], strict=True)
    if (
        network.version != 4
        or network.prefixlen != 32
        or not network.network_address.is_global
    ):
        raise ValueError("operatorCidr must be the operator public IPv4 /32")
    if not re.fullmatch(r"\d+\.\d+\.\d+", values["ubuntuImageVersion"]):
        raise ValueError(
            "Use an exact marketplace version, not latest or a placeholder"
        )
    if not values["sshPublicKey"].startswith(("ssh-ed25519 ", "ssh-rsa ")):
        raise ValueError("Provide a public SSH key")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("parameters", type=Path)
    args = parser.parse_args()
    validate(json.loads(args.parameters.read_text()))
    print("Deployment parameter checks passed; no Azure resources changed")
