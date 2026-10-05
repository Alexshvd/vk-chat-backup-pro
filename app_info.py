"""Public product and release metadata; never includes local archive settings."""
from urllib.parse import urlencode

APP_NAME = "VK Chat Backup Pro"
APP_VERSION = "1.0.0-beta.1"
HELPER_VERSION = "1.1.1"
REPOSITORY_URL = "https://github.com/Alexshvd/vk-chat-backup-pro"


def bug_report_url():
    return REPOSITORY_URL + "/issues/new?" + urlencode({
        "template": "bug_report.yml",
        "app_version": APP_VERSION,
        "helper_version": HELPER_VERSION,
    })


def feature_request_url():
    return REPOSITORY_URL + "/issues/new?template=feature_request.yml"
