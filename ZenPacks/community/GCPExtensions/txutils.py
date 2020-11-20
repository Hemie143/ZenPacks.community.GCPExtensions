##############################################################################
#
# Copyright (C) Zenoss, Inc. 2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from twisted.internet import defer
from twisted.internet import error
from twisted.internet import reactor


def txtimeout(deferred, seconds):
    """Raise TimeoutError on deferred after seconds.

    Returns original deferred.

    """

    def handle_timeout():
        deferred.cancel()

    timeout_d = reactor.callLater(seconds, handle_timeout)

    def handle_result(result):
        if timeout_d.active():
            timeout_d.cancel()

        return result

    deferred.addBoth(handle_result)

    def handle_failure(failure):
        if failure.check(defer.CancelledError):
            raise error.TimeoutError(string="timeout after %s seconds" % seconds)

        return failure

    deferred.addErrback(handle_failure)
    return deferred
