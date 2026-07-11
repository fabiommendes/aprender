from decimal import Decimal
from typing import IO, Any

import yaml


def dump_yaml(data: dict[str, Any], stream: IO[str]) -> None:
    """
    Dump the given data to a YAML stream using a custom SafeDumper.
    """
    yaml.dump(
        data,
        stream,
        indent=2,
        allow_unicode=True,
        encoding="utf-8",
        default_flow_style=False,
        sort_keys=False,
        Dumper=SafeDumper,
    )


class SafeDumper(yaml.SafeDumper):
    """
    A custom YAML SafeDumper that handles additional types like Decimal and multi-line strings.
    """


def string_representer(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    else:
        return dumper.represent_str(data)


def decimal_representer(dumper: yaml.SafeDumper, data: Decimal) -> yaml.Node:
    return dumper.represent_str(str(data))


SafeDumper.add_representer(str, string_representer)
SafeDumper.add_representer(Decimal, decimal_representer)
