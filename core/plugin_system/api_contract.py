from typing import NamedTuple


class APIVersion(NamedTuple):
    major: int
    minor: int

    def __str__(self):
        return f"{self.major}.{self.minor}"


CURRENT_API_VERSION = APIVersion(1, 0)


class APIContract:
    """Manages API version compatibility and deprecation warnings."""

    @staticmethod
    def check_compatibility(plugin_api_version_str: str) -> bool:
        try:
            major, minor = map(int, plugin_api_version_str.split("."))
            plugin_version = APIVersion(major, minor)

            # Simple rule: Major must match, Minor must be <= current
            if plugin_version.major != CURRENT_API_VERSION.major:
                return False
            return plugin_version.minor <= CURRENT_API_VERSION.minor
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def get_warning(plugin_api_version_str: str) -> str:
        # Placeholder for future deprecation warnings
        return ""
