
# Default Exports - Other symbols should be considered private to the module.
__all__ = [
    "ClientExt",
]

# stdlib Imports
import logging

# ZenPack Imports
from ZenPacks.zenoss.GoogleCloudPlatform.txgcp import Client, TokenManager, ComputeRequest, ComputeEndpoint, Request

# Service URLs
PUBSUB_API = "https://pubsub.googleapis.com"
CLOUDSQL_API = "https://sqladmin.googleapis.com/sql/v1beta4"

# Auth Scopes
SCOPE_CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"

LOG = logging.getLogger("zen.GCPExtensions")


class ClientExt(Client):
    def cloudsql(self, project):
        return CloudSQL(self, project)

    def subscriptions(self, project):
        LOG.debug('XXXX subscriptions project: {}'.format(project))
        return PubSubscription(self, project)

# Request Types ##############################################################

class CloudSQLRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        super(CloudSQLRequest, self).__init__(
            client=client,
            url="{}/{}".format(CLOUDSQL_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)


class PubSubscriptionRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        LOG.debug('XXXXX PubSubscriptionRequest')
        LOG.debug('XXXXX PubSubscriptionRequest url: {}'.format("{}/{}".format(PUBSUB_API, path)))

        super(PubSubscriptionRequest, self).__init__(
            client=client,
            url="{}/{}".format(PUBSUB_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)


# Request Issuer Types #######################################################

class CloudSQL(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def instances(self):
        return CloudSQLRequest(
            client=self.client,
            path="projects/{}/instances".format(
                self.project)).request()

    def databases(self, instance):
        return CloudSQLRequest(
            client=self.client,
            path="projects/{}/instances/{}/databases".format(
                self.project, instance)).request()


class PubSubscription(object):
    def __init__(self, client, project):
        LOG.debug('XXXX PubSubscription __init__')
        self.client = client
        self.project = project

    def instances(self):
        LOG.debug('XXXX PubSubscription instances')
        return PubSubscriptionRequest(
            client=self.client,
            path="v1/{}/subscriptions".format(
                self.project)).request()
