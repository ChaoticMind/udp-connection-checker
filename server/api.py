import logging
import json
from collections import OrderedDict

from twisted.web import server, resource
from twisted.web.util import redirectTo
from prometheus_client.twisted import MetricsResource

log = logging.getLogger(__name__)


class HttpApi(resource.Resource):
    """Root resource"""
    def __init__(self, conn, state):
        super(HttpApi, self).__init__()
        self.putChild(b"help", GenerateHelp())
        self.putChild(b"metrics", MetricsResource())
        self.putChild(b"status", Status(state))
        self.putChild(b"reset", Reset(conn))

    def getChild(self, name, req):
        return self

    def render_GET(self, request):
        log.debug('[HTTP API]: Received "/" request')
        return redirectTo(b"help", request)


class GenerateHelp(resource.Resource):
    """Simple resource displaying possible api calls"""
    isLeaf = True

    def render_GET(self, request):
        log.debug('[HTTP API]: Received "help" request')
        help_str = OrderedDict()  # can use {} in python3.6+
        help_str['/help'] = "Lists API calls (this message)"
        help_str['/metrics'] = "Lists metrics"
        help_str['/status'] = "Lists status"
        help_str['/reset'] = "Disconnects from client"
        request.responseHeaders.addRawHeader(
            b"content-type", b"application/json")
        return bytes("{}".format(json.dumps(help_str)), "utf-8")


class Status(resource.Resource):
    """Human readable metric data"""
    isLeaf = True

    def __init__(self, state):
        super().__init__()
        self.__state = state

    def render_GET(self, request):
        log.debug('[HTTP API]: Received "status" request')
        request.responseHeaders.addRawHeader(
            b"content-type", b"application/json")
        return bytes(repr(self.__state), 'utf-8')


class Reset(resource.Resource):
    """Drop connection to the client, forcing a new handshake"""
    isLeaf = True

    def __init__(self, conn):
        super().__init__()
        self.__conn = conn

    def render_GET(self, request):
        log.debug('[HTTP API]: Received "reset" request')
        if self.__conn.source_ip:
            self.__conn.reset_connection(request)
            return server.NOT_DONE_YET
        else:
            return b"Connection to client not yet initialized"
