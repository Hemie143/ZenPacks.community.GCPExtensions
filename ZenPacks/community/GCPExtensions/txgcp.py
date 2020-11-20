##############################################################################
#
# Copyright (C) Zenoss, Inc. 2016-2019, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

# Default Exports - Other symbols should be considered private to the module.
__all__ = [
    "Client",
    "RequestError",
]

# stdlib Imports
import collections
import itertools
import json
import logging
import os
import re
import time
import urllib
import urlparse

# Twisted Imports
from twisted.internet import defer
from twisted.web.client import getPage
from twisted.web.error import Error as TxWebError

# ZenPack Imports
from . import jwt
from .txutils import txtimeout
from .utils import maybe_bounded

# Service URLs
COMPUTE_API = "https://www.googleapis.com/compute/v1"
MONITORING_API = "https://monitoring.googleapis.com/v3"
KUBERNETES_API = "https://container.googleapis.com"
PUBSUB_API = "https://pubsub.googleapis.com"
SERVICE_API = "https://servicemanagement.googleapis.com"
BIGQUERY_API = "https://www.googleapis.com/bigquery/v2"
CLOUDFUNCTIONS_API = "https://cloudfunctions.googleapis.com"
DATAFLOW_API = "https://dataflow.googleapis.com"
STORAGE_API = "https://www.googleapis.com/storage/v1"
BIGTABLE_API = "https://bigtableadmin.googleapis.com/v2"
LOGGING_API = "https://logging.googleapis.com/v2"
CLOUDSQL_API = "https://sqladmin.googleapis.com/sql/v1beta4"
# Auth Scopes
SCOPE_COMPUTE = "https://www.googleapis.com/auth/compute"
SCOPE_COMPUTE_READONLY = "https://www.googleapis.com/auth/compute.readonly"
SCOPE_MONITORING_READ = "https://www.googleapis.com/auth/monitoring.read"
SCOPE_CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"

# Timeout for requests in seconds.
REQUEST_TIMEOUT = 60

LOG = logging.getLogger("zen.GoogleCloudPlatform")


class Client(object):
    def __init__(
            self,
            client_email=None,
            private_key=None,
            compute_maxResults=None,
            monitoring_pageSize=None,
            service_pageSize=None,
            save_responses=False,
            mock_responses=False,
            timeout=None):

        self.token_manager = TOKEN_MANAGER
        if timeout:
            self.timeout = timeout
        else:
            self.timeout = REQUEST_TIMEOUT

        if not (client_email and private_key):
            # Only attempt to load credentials if they weren't supplied.
            credentials = load_credentials()
        else:
            credentials = {}

        self.client_email = client_email or credentials.get("client_email")
        self.private_key = private_key or credentials.get("private_key")

        self.compute_maxResults = maybe_bounded(
            compute_maxResults,
            minimum=10,
            maximum=500)

        self.monitoring_pageSize = maybe_bounded(
            monitoring_pageSize,
            minimum=100,
            maximum=100000)

        self.service_pageSize = 100

        self.save_responses = save_responses

        if mock_responses:
            self.mock_responses = load_mock_responses()
        else:
            self.mock_responses = {}

    def compute_project(self, project):
        return ComputeProject(self, project)

    def compute_region(self, project, region):
        return ComputeRegion(self, project, region)

    def compute_regionInstanceGroup(self, project, region, instanceGroup):
        return ComputeRegionInstanceGroup(self, project, region, instanceGroup)

    def compute_zone(self, project, zone):
        return ComputeZone(self, project, zone)

    def compute_instanceGroup(self, project, zone, instanceGroup):
        return ComputeInstanceGroup(self, project, zone, instanceGroup)

    def kubernetes(self, project):
        return Kubernetes(self, project)

    def cloudsql(self, project):
        return CloudSQL(self, project)

    def subscriptions(self, project):
        LOG.debug('XXXX subscriptions project: {}'.format(project))
        return PubSubscription(self, project)

    def storage(self, project):
        return Storage(self, project)

    def cloudfunctions(self, project):
        return CloudFunctions(self, project)

    def autoscalars(self, project):
        return Autoscalars(self, project)

    def dataflow(self, project):
        return Dataflow(self, project)

    def bigquery(self, project):
        return BigQuery(self, project)

    def bigtable(self, project):
        return BigTable(self, project)

    def logging(self, project):
        return LoggingProject(self, project)

    def get(self, url, scope):
        return self.request(
            method="GET",
            url=url,
            data=None,
            scope=scope)

    def post(self, url, data, scope):
        return self.request(
            method="POST",
            url=url,
            data=data,
            scope=scope)

    def request(self, method, url, data, scope, attempt=1):
        if url and self.mock_responses:
            mock_response = self.mock_responses.get(url.split("?", 1)[0])
            if mock_response:
                d = defer.succeed(mock_response)
                d.addCallback(self.onResponse, url)
                return d

        d = self.token_manager.get_token(
            client_email=self.client_email,
            private_key=self.private_key,
            scope=scope)

        d.addCallback(
            self.request_with_token,
            method,
            url,
            data,
            scope,
            attempt)

        return d

    def request_with_token(self, token, method, url, data, scope, attempt):
        get_page_d = getPage(
            url,
            method=method,
            postdata=data,
            headers={
                "Authorization": "Bearer {}".format(token),
                "Accept": "application/json",
                "Content-Type": "application/json"})

        d = txtimeout(get_page_d, self.timeout)
        d.addCallback(self.onResponse, url)
        d.addErrback(
            self.onFailure,
            method,
            url,
            data,
            scope,
            attempt)

        return d

    def onResponse(self, result, url):
        if self.save_responses:
            save_response(url, result)

        return json.loads(result)

    def onFailure(self, failure, method, url, data, scope, attempt):
        if not failure.check(TxWebError):
            return failure

        try:
            status = int(failure.value.status)
            response = json.loads(failure.value.response)
            error = response.get("error", {})
        except Exception:
            return failure

        # 401 Unauthorized - could be because our token is no longer valid.
        if status == 401 and attempt <= 1:
            # TODO: Can we tell when a 401 shouldn't be a token invalidation?
            self.token_manager.invalidate_token(
                client_email=self.client_email,
                private_key=self.private_key,
                scope=scope)

            # Retry the request after invalidating the token.
            return self.request(method, url, data, scope, attempt=attempt + 1)

        if status == 403 and attempt <= 1:
            # 403 is an access issue. Inform the user and return {}
            clean_url = re.sub('\?.*', '', url)
            LOG.error("Required GCP access failed for: %s!", clean_url)

        raise RequestError(
            error.get("message", str(failure.value)),
            error.get("code", status),
            error.get("status"),
            error.get("details"),
            failure.value)


class RequestError(Exception):
    def __init__(self, msg, code, status, details, original):
        super(RequestError, self).__init__(msg)
        self.code = code
        self.status = status
        self.details = details
        self.original = original


class TokenManager(object):
    Credentials = collections.namedtuple(
        "Credentials", [
            "client_email",
            "private_key",
            "scope"])

    Token = collections.namedtuple(
        "Token", [
            "access_token",
            "expiration"])

    def __init__(self):
        self.tokens = {}
        self.locks = collections.defaultdict(defer.DeferredLock)

    def get_token(self, client_email, private_key, scope):
        credentials = self.Credentials(client_email, private_key, scope)

        # Ensure that only we don't try to simultaneously request multiple
        # tokens for the same set of credentials.
        d = self.locks[credentials].acquire()
        d.addCallback(self.onTokenLockAcquired, credentials)
        return d

    def invalidate_token(self, client_email, private_key, scope):
        LOG.debug(
            "invalidating token (client_email=%s, scope=%s)",
            client_email,
            scope)

        credentials = self.Credentials(client_email, private_key, scope)
        self.tokens.pop(credentials, None)

    def onTokenLockAcquired(self, _, credentials):
        # Invalidate any existing token that will expire soon.
        token = self.tokens.get(credentials)
        if token:
            now = time.time()
            if token.expiration < (now + 60):
                LOG.debug(
                    "expiring token (client_email=%s, scope=%s)",
                    credentials.client_email,
                    credentials.scope)

                self.tokens.pop(credentials, None)

        # Immediately return existing token if it *should* still be valid.
        token = self.tokens.get(credentials)
        if token:
            self.locks[credentials].release()
            return defer.succeed(token.access_token)

        # Go get a new token.
        LOG.debug(
            "requesting token (client_email=%s, scope=%s)",
            credentials.client_email,
            credentials.scope)

        get_page_d = getPage(
            "https://www.googleapis.com/oauth2/v4/token",
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
            postdata=urllib.urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": jwt.get_assertion(
                    credentials.client_email,
                    credentials.scope,
                    credentials.private_key)}))

        # Add a timeout to getPage call.
        d = txtimeout(get_page_d, REQUEST_TIMEOUT)

        d.addCallback(self.onTokenSuccess, credentials)
        d.addBoth(self.onTokenResult, credentials)
        return d

    def onTokenSuccess(self, result, credentials):
        LOG.debug(
            "received token (client_email=%s, scope=%s)",
            credentials.client_email,
            credentials.scope)

        result = json.loads(result)
        self.tokens[credentials] = self.Token(
            access_token=result["access_token"],
            expiration=time.time() + result["expires_in"])

        # Clean up any expired or soon-to-expire tokens.
        now = time.time()
        for c, t in self.tokens.items():
            if t.expiration < (now + 60):
                LOG.debug(
                    "expiring token (client_email=%s, scope=%s)",
                    c.client_email,
                    c.scope)

                self.tokens.pop(c, None)

        return result["access_token"]

    def onTokenResult(self, result, credentials):
        self.locks[credentials].release()
        return result


# Singleton that allows sharing of tokens among Client instances.
TOKEN_MANAGER = TokenManager()


# Request Types ##############################################################

class Request(object):
    BASE_URL = "https://www.googleapis.com"
    SCOPE = SCOPE_CLOUD_PLATFORM

    def __init__(
            self,
            client,
            url=None,
            path=None,
            method="GET",
            data=None,
            scope=None):

        self.client = client

        if url:
            self.url = url
        elif path:
            self.url = "{}/{}".format(self.BASE_URL, path)
        else:
            self.url = self.BASE_URL

        self.method = method

        # Google requires Content-Length be set on POST requests, and Twisted
        # won't set Content-Length if data is None.
        if data is None and method == "POST":
            self.data = ""
        else:
            self.data = data

        self.scope = scope or self.SCOPE

    def request(self):
        return self.client.request(
            method=self.method,
            url=self.url,
            data=self.data,
            scope=self.scope)


class ComputeRequest(Request):
    BASE_URL = COMPUTE_API
    SCOPE = SCOPE_COMPUTE_READONLY

    def request(self):
        if self.client.compute_maxResults:
            first_page_url = "{}?maxResults={}".format(
                self.url,
                self.client.compute_maxResults)
        else:
            first_page_url = self.url

        d = self.client.request(
            method=self.method,
            url=first_page_url,
            data=self.data,
            scope=self.scope)

        d.addCallback(self.handle_page)
        return d

    def handle_page(self, result, page=1, items=None):
        if items is None:
            items = []

        if "items" in result:
            items.extend(result["items"])

        nextPageToken = urllib.quote_plus(result.pop("nextPageToken", ""))

        if nextPageToken:
            if self.client.compute_maxResults:
                next_page_url = "{}?maxResults={}&pageToken={}".format(
                    self.url,
                    self.client.compute_maxResults,
                    nextPageToken)
            else:
                next_page_url = "{}?pageToken={}".format(
                    self.url,
                    nextPageToken)

            d = self.client.request(
                method=self.method,
                url=next_page_url,
                data=self.data,
                scope=self.scope)

            d.addCallback(self.handle_page, page=page + 1, items=items)
        else:
            result["items"] = items
            d = defer.succeed(result)

        return d


class KubernetesRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        super(KubernetesRequest, self).__init__(
            client=client,
            url="{}/v1/{}".format(KUBERNETES_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)


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


class CloudFunctionsRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        super(CloudFunctionsRequest, self).__init__(
            client=client,
            url="{}/v1/{}".format(CLOUDFUNCTIONS_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)


class AutoscalarRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        super(AutoscalarRequest, self).__init__(
            client=client,
            url="{}/{}".format(COMPUTE_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)


class StorageRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        super(StorageRequest, self).__init__(
            client=client,
            url="{}/{}".format(STORAGE_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)


class DataflowRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        super(DataflowRequest, self).__init__(
            client=client,
            url="{}/v1b3/{}".format(DATAFLOW_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_COMPUTE_READONLY)


class TypesRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        super(TypesRequest, self).__init__(
            client=client,
            url="{}/{}".format(MONITORING_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)


class BigQueryRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        super(BigQueryRequest, self).__init__(
            client=client,
            url="{}/{}".format(BIGQUERY_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)


class ServicesRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        super(ServicesRequest, self).__init__(
            client=client,
            url="{}/v1/{}".format(SERVICE_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)

    def request(self):
        if self.client.service_pageSize:
            first_page_url = "{}?pageSize={}".format(
                self.url,
                self.client.service_pageSize)
        else:
            first_page_url = self.url

        d = self.client.request(
            method=self.method,
            url=first_page_url,
            data=self.data,
            scope=self.scope)

        d.addCallback(self.handle_page)
        return d

    def handle_page(self, result, page=1, items=None):
        if items is None:
            items = []
        if "services" in result:
            items_key = "services"
        else:
            return result

        items.extend(result[items_key])

        nextPageToken = urllib.quote_plus(result.pop("nextPageToken", ""))

        if nextPageToken:
            if self.client.service_pageSize:
                next_page_url = "{}?pageSize={}&pageToken={}".format(
                    self.url,
                    self.client.service_pageSize,
                    nextPageToken)
            else:
                next_page_url = "{}?pageToken={}".format(
                    self.url,
                    nextPageToken)

            d = self.client.request(
                method=self.method,
                url=next_page_url,
                data=self.data,
                scope=self.scope)

            d.addCallback(self.handle_page, page=page + 1, items=items)
        else:
            result[items_key] = items
            return result

        return d


class LoggingRequest(Request):
    def __init__(self, client, path, method="POST", data=None, scope=None):
        super(LoggingRequest, self).__init__(
            client=client,
            url=path,
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)

    def request(self):
        d = self.client.post(
            url=self.url,
            data=jwt.json_encode(self.data),
            scope=self.scope)

        d.addCallback(self.handle_page)
        return d

    def handle_page(self, result, page=1, items=None):
        if items is None:
            items = []
        if "entries" in result:
            items_key = "entries"
        else:
            return result

        items.extend(result[items_key])
        nextPageToken = result.pop("nextPageToken", "")

        if nextPageToken:
            self.data['pageToken'] = nextPageToken
            d = self.client.post(
                url=self.url,
                data=jwt.json_encode(self.data),
                scope=self.scope)

            d.addCallback(self.handle_page, page=page + 1, items=items)
        else:
            result[items_key] = items
            return result

        return d


class BigTableRequest(Request):
    def __init__(self, client, path, method="GET", data=None, scope=None):
        super(BigTableRequest, self).__init__(
            client=client,
            url="{}/{}".format(BIGTABLE_API, path),
            method=method,
            data=data,
            scope=scope if scope else SCOPE_CLOUD_PLATFORM)


class MonitoringRequest(Request):
    BASE_URL = MONITORING_API
    SCOPE = SCOPE_MONITORING_READ

    def request(self):
        # MONITORING_API/projects/zenoss-testing-1/timeSeries?pageSize=100&view=FULL
        if self.client.monitoring_pageSize:
            first_page_url = "{}&pageSize={}".format(
                self.url,
                self.client.monitoring_pageSize)
        else:
            first_page_url = self.url

        d = self.client.request(
            method=self.method,
            url=first_page_url,
            data=self.data,
            scope=self.scope)

        d.addCallback(self.handle_page)
        return d

    def handle_page(self, result, page=1, items=None):
        if items is None:
            items = []

        if "timeSeries" in result:
            items_key = "timeSeries"
        else:
            return result

        items.extend(result[items_key])

        nextPageToken = urllib.quote_plus(result.pop("nextPageToken", ""))

        if nextPageToken:
            if self.client.monitoring_pageSize:
                next_page_url = "{}&pageSize={}&pageToken={}".format(
                    self.url,
                    self.client.monitoring_pageSize,
                    nextPageToken)
            else:
                next_page_url = "{}&pageToken={}".format(
                    self.url,
                    nextPageToken)

            d = self.client.request(
                method=self.method,
                url=next_page_url,
                data=self.data,
                scope=self.scope)

            d.addCallback(self.handle_page, page=page + 1, items=items)
        else:
            result[items_key] = items
            return result

        return d


# Request Issuer Types #######################################################

class ComputeEndpoint(object):
    PATH_ELEMENTS = ()
    DEFAULT_SCOPE = SCOPE_COMPUTE_READONLY

    def __init__(self, client, *args):
        self.client = client
        self.path = "/".join(
            itertools.chain.from_iterable(
                itertools.izip(self.PATH_ELEMENTS, args)))

    def get(self, path=None, scope=None):
        return self.request("GET", path=path, scope=scope)

    def post(self, path=None, scope=None):
        return self.request("POST", path=path, scope=scope)

    def request(self, method, path=None, scope=None):
        if path:
            full_path = "/".join((self.path, path))
        else:
            full_path = self.path

        return ComputeRequest(
            self.client,
            path=full_path,
            method=method,
            scope=scope or self.DEFAULT_SCOPE).request()


class ComputeProject(ComputeEndpoint):
    PATH_ELEMENTS = ("projects",)

    def list(self, collection):
        return self.get(collection)

    def global_list(self, collection):
        return self.get("global/{}".format(collection))

    def aggregated_list(self, collection):
        return self.get("aggregated/{}".format(collection))


class Autoscalars(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def aggregatedList(self):
        return AutoscalarRequest(
            client=self.client,
            path="projects/{}/aggregated/autoscalers".format(
                self.project)).request()


class Storage(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def buckets(self):
        return StorageRequest(
            client=self.client,
            path="b?project={}".format(
                self.project)).request()

    def objects(self, bucket):
        return StorageRequest(
            client=self.client,
            path="b/{}/o".format(
                bucket)).request()


class BigTable(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def instances(self):
        return BigTableRequest(
            client=self.client,
            path="projects/{}/instances".format(
                self.project)).request()

    def clusters(self):
        return BigTableRequest(
            client=self.client,
            path="projects/{}/instances/-/clusters".format(
                self.project)).request()

    def appProfiles(self):
        return BigTableRequest(
            client=self.client,
            path="projects/{}/instances/-/appProfiles".format(
                self.project)).request()

    def tables(self, instance):
        return BigTableRequest(
            client=self.client,
            path="projects/{}/instances/{}/tables".format(
                self.project, instance)).request()


class ComputeRegion(ComputeEndpoint):
    PATH_ELEMENTS = ("projects", "regions")

    def list(self, collection):
        return self.get(collection)


class ComputeRegionInstanceGroup(ComputeEndpoint):
    PATH_ELEMENTS = ("projects", "regions", "instanceGroups")

    def listInstances(self):
        d = self.post("listInstances")

        def add_path(result):
            result[u'path'] = self.path
            return result

        # We must add instance group's path because the result doesn't contain
        # any information about the instance group for which the instances are
        # being listed.
        d.addCallback(add_path)

        return d


class ComputeZone(ComputeEndpoint):
    PATH_ELEMENTS = ("projects", "zones")

    def list(self, collection):
        return self.get(collection)


class ComputeInstanceGroup(ComputeEndpoint):
    PATH_ELEMENTS = ("projects", "zones", "instanceGroups")

    def listInstances(self):
        d = self.post("listInstances")

        def add_path(result):
            result[u'path'] = self.path
            return result

        # We must add instance group's path because the result doesn't contain
        # any information about the instance group for which the instances are
        # being listed.
        d.addCallback(add_path)

        return d


class Kubernetes(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def clusters(self):
        return KubernetesRequest(
            client=self.client,
            path="projects/{}/locations/-/clusters".format(
                self.project)).request()


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


class CloudFunctions(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def functions(self):
        return CloudFunctionsRequest(
            client=self.client,
            path="projects/{}/locations/-/functions".format(
                self.project)).request()


class Dataflow(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def jobs(self):
        return DataflowRequest(
            client=self.client,
            path="projects/{}/jobs:aggregated".format(
                self.project)).request()


class BigQuery(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def list(self):
        """ Query for BigQuery list"""
        path = "projects/{}/datasets".format(self.project)
        return BigQueryRequest(
            client=self.client,
            path=path).request()

    def dataset(self, dataset_id):
        """ Query for details of a BigQuery dataset """
        path = "projects/{}/datasets/{}".format(self.project, dataset_id)
        return self.request(path)

    def request(self, path=None):
        """ Issue a BigQuery Request """
        return BigQueryRequest(
            client=self.client,
            path=path).request()


class ServicesProject(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def services(self):
        return ServicesRequest(
            client=self.client,
            path="services").request()


class TypesProject(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def types(self, filter_=None,):
        query = {
            "filter": filter_,
        }
        return TypesRequest(
            client=self.client,
            path="projects/{project}/metricDescriptors?{query}".format(
                project=self.project,
                query=urllib.urlencode(query))).request()


class BigQueryProject(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def table(self, data):

        return self.client.post(
            url='{}/projects/{}/queries'.format(
                BIGQUERY_API, self.project),
            data=jwt.json_encode(data),
            scope=SCOPE_CLOUD_PLATFORM)


class LoggingProject(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def instancelogs(self, start, end):

        data = {
              "resourceNames": [
                "projects/{}".format(self.project)
              ],
              "filter": "protoPayload.@type=type.googleapis.com/google.cloud.audit.AuditLog "
                        "AND resource.type=gce_instance "
                        "AND protoPayload.methodName:(compute.instances) "
                        "AND operation.last=true "
                        "AND timestamp>\"{}\" AND timestamp<=\"{}\"".format(start.isoformat("T") + "Z", end.isoformat("T") + "Z"),
              "pageToken": ""
            }
        return self.entries(data)

    def entries(self, data):
        return LoggingRequest(
            client=self.client,
            path='{}/entries:list'.format(
                LOGGING_API),
            data=data,
            scope=SCOPE_CLOUD_PLATFORM).request()


class MonitoringProject(object):
    def __init__(self, client, project):
        self.client = client
        self.project = project

    def timeSeries(
            self,
            filter_=None,
            perSeriesAligner=None,
            crossSeriesReducer=None,
            groupByFields=None,
            start=None,
            end=None):

        alignment_seconds = int((end - start).total_seconds())
        alignment_period = str(alignment_seconds) + 's'

        query = [
            ("filter", filter_),
            ("aggregation.alignmentPeriod", alignment_period),
            ("fields", "nextPageToken,timeSeries(metric,points,resource)"),
            ("interval.startTime", "{}Z".format(start.isoformat())),
            ("interval.endTime", "{}Z".format(end.isoformat())),
            ("view", "FULL"),
        ]

        if perSeriesAligner:
            query.append(("aggregation.perSeriesAligner", perSeriesAligner))
        if crossSeriesReducer:
            query.append(("aggregation.crossSeriesReducer", crossSeriesReducer))
        if groupByFields:
            for groupByField in groupByFields:
                query.append(("aggregation.groupByFields", groupByField))

        return MonitoringRequest(
            client=self.client,
            path="projects/{project}/timeSeries?{query}".format(
                project=self.project,
                query=urllib.urlencode(query))).request()


class Subscription(object):
    def __init__(self, client, project, name):
        self.client = client
        self.project = project
        self.name = name

    def pull(self, max_messages=1):
        """
        Pulls messages from the server.

        Documentation:
        https://cloud.google.com/pubsub/docs/reference/rest/v1/projects.subscriptions/pull
        """
        data = {'maxMessages': max_messages, 'returnImmediately': True}

        return self.client.post(
            url='{}/v1/projects/{}/subscriptions/{}:pull'.format(
                PUBSUB_API, self.project, self.name),
            data=jwt.json_encode(data),
            scope=SCOPE_CLOUD_PLATFORM)

    def acknowledge(self, ack_ids):
        """
        Acknowledges the messages with associated `ack_ids`.

        Documentation:
        https://cloud.google.com/pubsub/docs/reference/rest/v1/projects.subscriptions/acknowledge
        """
        data = {'ackIds': ack_ids}

        return self.client.post(
            url='{}/v1/projects/{}/subscriptions/{}:acknowledge'.format(
                PUBSUB_API, self.project, self.name),
            data=jwt.json_encode(data),
            scope=SCOPE_CLOUD_PLATFORM)


def load_credentials():
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        return {}

    with open(credentials_path, "r") as credentials_file:
        return json.load(credentials_file)


# Simulation Utilities #######################################################

def save_response(url, response):
    responses_dir = "-".join((os.path.splitext(__file__)[0], "responses"))
    response_path = "{}.json".format(
        os.path.join(
            responses_dir,
            urlparse.urlparse(url).netloc,
            urlparse.urlparse(url).path.lstrip("/")
            ))

    response_dir = os.path.dirname(response_path)

    if not os.path.isdir(response_dir):
        os.makedirs(response_dir)

    with open(response_path, "w") as response_file:
        data = json.loads(response)
        response_file.write(json.dumps(data, indent=2, sort_keys=True))


def load_mock_responses():
    responses_dir = "-".join((os.path.splitext(__file__)[0], "responses"))
    if not os.path.isdir(responses_dir):
        return {}

    mock_responses = {}

    for root, _dirs, files in os.walk(responses_dir):
        url_prefix = root.replace(responses_dir, "").strip("/")
        for filename in files:
            filename_prefix, extension = os.path.splitext(filename)
            if extension != ".json":
                continue

            url_path = os.path.join('https://', url_prefix, filename_prefix)

            with open(os.path.join(root, filename), "r") as response_file:
                mock_responses[url_path] = response_file.read()

    return mock_responses
