"""Include yt-dlp; FFmpeg is supplied by the existing shared delivery plan."""
from delivery_contract import DeliveryContribution


def contribution(target):
    return DeliveryContribution(
        hidden_imports=('modules.youtube.worker',),
        collect_packages=('yt_dlp',),
        metadata_packages=('yt-dlp',))
