"""Combine suite resources with registered module delivery requirements."""
from delivery_contract import DeliveryContribution, PortableTool
from module_registry import delivery_contributions


def delivery_plan(target: str) -> DeliveryContribution:
    contributions = (*delivery_contributions(target), DeliveryContribution(
        helpers=(("Folder picker", "scripts/windows_folder_picker.py"),),
        hidden_imports=("server", "runtime_logging"),
        tools=(PortableTool("ffmpeg", "-version"),),
    ))
    return DeliveryContribution(**{
        field: tuple(item for contribution in contributions for item in getattr(contribution, field))
        for field in DeliveryContribution.__dataclass_fields__
    })
