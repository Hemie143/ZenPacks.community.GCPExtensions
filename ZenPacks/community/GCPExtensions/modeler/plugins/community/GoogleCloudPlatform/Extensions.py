"""Models Google Cloud Platform extra resources."""

# Default Exports
__all__ = [
    "Extensions",
]


# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin

# ZenPack Imports
from ZenPacks.community.GCPExtensions import modeling
from ZenPacks.zenoss.GoogleCloudPlatform.modeler.plugins.GoogleCloudPlatform.Project import Project
from ZenPacks.zenoss.GoogleCloudPlatform.utils import (
    valid_project_id,
    valid_email_address,
    valid_private_key,
)


class Extensions(Project):
    required_properties = (
        "zGoogleCloudPlatformProjectId",
        "zGoogleCloudPlatformClientEmail",
        "zGoogleCloudPlatformPrivateKey",
        "zGoogleCloudPlatformComputeMaxResults",
    )

    deviceProperties = (
        PythonPlugin.deviceProperties +
        required_properties)

    def collect(self, device, log):
        project_id = getattr(device, "zGoogleCloudPlatformProjectId", None)
        client_email = getattr(device, "zGoogleCloudPlatformClientEmail", None)
        private_key = getattr(device, "zGoogleCloudPlatformPrivateKey", None)

        if not project_id:
            log.error("%s: project ID is not configured", device.id)
            return

        if not valid_project_id(project_id):
            log.error("%s: %r is not a valid project ID", device.id, project_id)
            return

        if not client_email:
            log.error("%s: client email address is not configured", device.id)
            return

        if not valid_email_address(client_email):
            log.error("%s: %r is not a valid client email address", device.id, client_email)
            return

        if not private_key:
            log.error("%s: private key is not configured", device.id)
            return

        if not valid_private_key(private_key):
            log.error("%s: invalid private key", device.id)
            return

        log.info(
            "%s: collecting data from Google Cloud Platform APIs (CloudSQL)",
            device.id)

        collector = modeling.CollectorExt(device)
        d = collector.collect(device.zGoogleCloudPlatformProjectId)
        d.addErrback(self.handle_failure, device, log)
        return d


    def process(self, device, results, log):
        log.info("%s: processing collected data", device.id)
        return modeling.process(device, results, self.name())
