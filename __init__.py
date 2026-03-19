import importlib.util
from pathlib import Path


def _load_legacy_module():
    module_name = f"{__package__}._gn_groups_legacy" if __package__ else "gn_groups_legacy"
    module_path = Path(__file__).with_name("GN Groups.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load legacy module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    module.__package__ = __package__
    spec.loader.exec_module(module)
    return module


_legacy_module = _load_legacy_module()

for _name in dir(_legacy_module):
    if _name.startswith("__") and _name not in {"__all__", "__doc__"}:
        continue
    globals()[_name] = getattr(_legacy_module, _name)


if __name__ == "__main__":
    register()
