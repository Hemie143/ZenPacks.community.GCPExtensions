
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
REDIS_API = "https://redis.googleapis.com"

# Auth Scopes
SCOPE_CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"

LOG = logging.getLogger("zen.GCPExtensions")


class ClientExt(Client):
    def cloudsql(self, project):
        return CloudSQL(self, project)

    def subscriptions(self, project):
        return PubSubscription(self, project)

    def memorystore(self, project):
        return MemoryStore(self, project)

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
        super(PubSubscriptionRequest, self).__init__(
            client=client,
            url="{}/{}".format(PUBSUB_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)


class MemoryStoreRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        LOG.debug('MemoryStoreRequest url: {}'.format("{}/{}".format(REDIS_API, path)))
        super(MemoryStoreRequest, self).__init__(
            client=client,
            url="{}/{}".format(REDIS_API, path),
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
        self.client = client
        self.project = project

    def topics(self):
        return PubSubscriptionRequest(
            client=self.client,
            path="v1/projects/{}/topics".format(
                self.project)).request()

    def subscriptions(self):
        return PubSubscriptionRequest(
            client=self.client,
            path="v1/projects/{}/subscriptions".format(
                self.project)).request()


class MemoryStore(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def locations(self):
        return MemoryStoreRequest(
            client=self.client,
            path="v1/projects/{}/locations".format(
                self.project)).request()

    def instances(self):
        return MemoryStoreRequest(
            client=self.client,
            path="v1/projects/{}/locations/-/instances".format(
                self.project)).request()
