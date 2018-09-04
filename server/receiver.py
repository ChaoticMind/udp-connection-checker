import logging
import json

from twisted.internet import task
from twisted.internet.protocol import DatagramProtocol

from client import MTU

log = logging.getLogger(__name__)


class Receiver(DatagramProtocol):
    def __init__(self, nolock, state_handler):
        super().__init__()
        self.__initialized = False
        self.source_ip = None
        self.__source_port = None
        self.__lock_port = not nolock
        self.__state = state_handler
        self.__expect_task = task.LoopingCall(self.__state.expect_packet)
        self.__reset_task = None
        self.__pending_reset = None

    def datagramReceived(self, data, info):
        # Step 1: lock/verify
        host, port = info
        # log.debug("Received {} from {}:{}".format(data, host, port))
        if self.source_ip or self.__source_port:
            if host != self.source_ip:
                log.error(
                    "Received packet from unknown ip " +
                    "({}, expected {}), ignoring".format(host, self.source_ip)
                )
                msg = {'type': 'info', 'content': "unknown ip, ignoring"}
                self._send_json(msg, info)
                return
            elif self.__lock_port and port != self.__source_port:
                log.error(
                    "Received packet from unknown port " +
                    "({}, expected {}), ignoring".format(
                        port, self.__source_port)
                )
                msg = {'type': 'info', 'content': "unknown port, ignoring"}
                self._send_json(msg, info)
                return
            else:  # correct ip:port
                pass
        else:
            log.info("Locking receipts to: {}:{}".format(host, port))
            self.source_ip = host
            self.__source_port = port

        # Step 2: strip
        delimiter = bytes('}', 'ascii')[0]
        for i, x in enumerate(data):  # find padding delimiter
            if x == delimiter:
                break
        if i < len(data) - 1:
            stripped = len(data) - (i + 1)
            data = data[:i + 1]  # strip padding
            log.debug(
                "Received: {} ({} bytes stripped)".format(data, stripped))
        else:
            log.debug("Received: {}".format(data))

        # Step 3: decode
        data = json.loads(data.decode("ascii"))
        if data['type'] == "handshake":
            if self.__initialized:
                log.warning("Already shook hands, resetting state...")
                self.__expect_task.stop()
                self.__state.reset_state()
                # return
            if self.__pending_reset:  # API waiting
                self.__pending_reset.write(
                    b"Successfully resetted session")  # inform API
                self.__pending_reset.finish()
                self.__pending_reset = None
                self.__reset_task.stop()
                self.__reset_task = None

            msg = {"type": "ack"}
            self.__initialized = True
            inv_pps = 1 / data['pps']
            self.__expect_task.start(inv_pps, now=True)
            self._send_json(msg, info)
        elif data['type'] == "next_packet":
            # TODO: if not initialized, initialize - guess
            self.__state.received(data['packet_id'], self)
        else:
            log.error("received unknown data: {}".format(data))

    def _send_json(self, data, info=None):
        encoded = bytes(json.dumps(data), "ascii")
        assert(len(encoded) <= MTU)
        if info is None:
            info = (self.source_ip, self.__source_port)
            if self.source_ip is None or self.__source_port is None:
                log.critical(
                    "Attempted to send a message with undefined destination")
                return
        log.debug("Sending {}".format(encoded))
        self.transport.write(encoded, info)

    def reset_connection(self, request):
        msg = {'type': "reset"}
        self.__pending_reset = request
        self.__reset_task = task.LoopingCall(self._send_json, msg)
        self.__reset_task.start(1, now=True)

    def abort_connection(self):
        msg = {'type': "abort"}
        self._send_json(msg)
