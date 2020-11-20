##############################################################################
#
# Copyright (C) Zenoss, Inc. 2016-2019, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Models Google Cloud Platform extra resources."""

# Default Exports
__all__ = [
    "Project",
    "Extensions",
]

# stdlib Imports
import json

# Twisted Imports
from twisted.python.failure import Failure as TxFailure
from twisted.web.error import Error as TxWebError

# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin

# ZenPack Imports
# from ZenPacks.zenoss.GoogleCloudPlatform import modeling
from ZenPacks.community.GCPExtensions import modeling
from ZenPacks.community.GCPExtensions.utils import (
    valid_project_id,
    valid_email_address,
    valid_private_key,
)


class Extensions(PythonPlugin):
    required_properties = (
        "zGoogleCloudPlatformProjectId",
        "zGoogleCloudPlatformClientEmail",
        "zGoogleCloudPlatformPrivateKey",
        "zGoogleCloudPlatformGuestUseExternalIP",
        "zGoogleCloudPlatformComputeMaxResults",
        "zGoogleCloudPlatformFunctionWhitelist",
        "zGoogleCloudPlatformDataflowJobNamesModeled",
        "zGoogleCloudPlatformBigQueryDatasetsModeled",
        "zGoogleCloudPlatformBigTableClustersModeled",
        "zGoogleCloudPlatformBigTableInstancesModeled",
        "zGoogleCloudPlatformBigTableAppProfilesModeled",
        "zGoogleCloudPlatformBigTableTablesModeled",
        "zGoogleCloudPlatformDiscoverGuests",
        "zGoogleCloudPlatformGuestLabels",
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
            "%s: collecting data from Google Cloud Platform APIs",
            device.id)

        collector = modeling.Collector(device)
        d = collector.collect(device.zGoogleCloudPlatformProjectId)
        d.addErrback(self.handle_failure, device, log)
        return d

    def handle_failure(self, failure, device, log):
        message = str(failure)
        if isinstance(failure, TxFailure):
            error = failure.value
            message = str(error)
            if isinstance(error, TxWebError):
                try:
                    response = json.loads(error.response)
                except (TypeError, ValueError):
                    pass
                else:
                    error_message = response.get("error")
                    error_description = response.get("error_description")

                    if error_message and error_description:
                        message = "{}: {}".format(
                            error_message,
                            error_description)
                    elif error_message:
                        message = error_message
                    elif error_description:
                        message = error_description

        log.error("%s: %s", device.id, message)

    def process(self, device, results, log):
        log.info("%s: processing collected data", device.id)
        return modeling.process(device, results, self.name())
