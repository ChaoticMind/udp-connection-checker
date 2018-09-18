import logging
import json

from twisted.internet import task
from twisted.internet.protocol import DatagramProtocol

from client import MTU

log = logging.getLogger(__name__)

PADDING_DELIMITER = '}'  # the received json ends with '}'


class Receiver(DatagramProtocol):
    def __init__(self, nolock, state_handler):
        super().__init__()
        self.source_ip = None
        self.__source_port = None
        self.__lock_port = not nolock
        self.__state = state_handler
        self.__expect_task = task.LoopingCall(self.__state.expect_packet)
        self._pending_reset_request = None

    def _verify_or_lock(self, info):
        host, port = info
        if self.source_ip or self.__source_port:
            if host != self.source_ip:
                log.error(
                    "Received packet from unknown ip " +
                    "({}, expected {}), ignoring".format(host, self.source_ip)
                )
                return {'type': 'info', 'content': "unknown ip, ignoring"}
            elif self.__lock_port and port != self.__source_port:
                log.error(
                    "Received packet from unknown port " +
                    "({}, expected {}), ignoring".format(
                        port, self.__source_port)
                )
                return {'type': 'info', 'content': "unknown port, ignoring"}

            else:  # correct ip:port
                return
        else:
            log.info("Locking receipts to: {}:{}".format(host, port))
            self.source_ip = host
            self.__source_port = port
            return

    @staticmethod
    def _strip_padding(data):
        i = data.index(PADDING_DELIMITER)
        if i < len(data) - 1:  # delimiter found before the last element
            n_stripped = len(data) - (i + 1)
            data = data[:i + 1]  # strip padding
            log.debug(
                "Received: {} ({} bytes stripped)".format(data, n_stripped))
        else:
            assert(data[len(data) - 1] == PADDING_DELIMITER)
            log.debug("Received: {}".format(data))
        return data

    def _process_handshake(self, pps):
        if self.__expect_task.running:
            log.warning("Already shook hands, re-initializing...")
            self.__expect_task.stop()

        if self._pending_reset_request:  # API waiting
            self._pending_reset_request.complete_reset_request()
            self._pending_reset_request = None

        self.__state.reset_state()
        inv_pps = 1 / pps
        d = self.__expect_task.start(inv_pps, now=True)
        d.addErrback(self.__expect_task_errback)
        return {"type": "ack"}

    def _process_next_packet(self, packet_id):
        self.__state.received(packet_id, self)

    def cleanup(self):
        if self.__expect_task.running:
            self.__expect_task.stop()

    def datagramReceived(self, data, info):
        # log.debug("Received {} from {}:{}".format(data, host, port))
        # Step 1: lock/verify
        ret = self._verify_or_lock(info)
        if ret is not None:
            self._send_json(ret, info)
            return

        # Step 2: decode
        try:
            decoded = data.decode("ascii")
        except AttributeError:
            log.error(
                "Received none ascii-encoded data: {}, ignoring".format(data))
            return

        # Step 3: strip
        try:
            stripped = self._strip_padding(decoded)
        except ValueError:
            log.error(
                "Could not find delimiter: '{}'"
                " in received (padded?) packet: {}. Bad json?".format(
                    PADDING_DELIMITER, decoded))
            return

        # Step 4: process packet
        data = json.loads(stripped)
        try:
            packet_type = data['type']
        except KeyError:
            log.error(
                "Could not find key 'type' in received json: {}".format(data))
            return

        if packet_type == "handshake":
            try:
                pps = int(data['pps'])
            except (KeyError, ValueError):
                log.error(
                    "Bad 'pps' key in handshake packet: {}".format(data))
                return
            msg = self._process_handshake(pps)
            if msg:
                self._send_json(msg, info)

        elif packet_type == "next_packet":
            try:
                packet_id = int(data['packet_id'])
            except (KeyError, ValueError):
                log.error(
                    "Bad 'packet_id' key in handshake packet: {}".format(data))
                return
            self._process_next_packet(packet_id)

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
        try:
            self.transport.write(encoded, info)
        except AttributeError:
            log.error("Could not send data to peer: {}".format(info))

    def reset_connection(self, request):
        self._pending_reset_request = ResetRequest(request, self._send_json)

    @staticmethod
    def __expect_task_errback(reason):
        log.error("expect_packet() failed with:")
        print(reason.getTraceback())

    def abort_connection(self):
        msg = {'type': "abort"}
        self._send_json(msg)


class ResetRequest:
    reset_retry_period_s = 1

    def __init__(self, request, task_callback):
        self._request = request
        msg = {'type': "reset"}
        self._reset_task = task.LoopingCall(task_callback, msg)
        d = self._reset_task.start(self.reset_retry_period_s, now=True)
        d.addErrback(self.__reset_task_errback)

    def complete_reset_request(self):
        self._request.write(b"Successfully resetted session")  # inform API
        self._request.finish()
        self._reset_task.stop()

    @staticmethod
    def __reset_task_errback(reason):
        log.error("reset_connection() failed with:")
        print(reason.getTraceback())
