import logging
import json
import functools

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

    def _verify(self, info):
        host, port = info
        if not self.source_ip or not self.__source_port:
            log.error(
                "Received non-handshake packet as a first packet. Ignoring..."
            )
            return False
        elif host != self.source_ip or port != self.__source_port:
            log.error(
                "Received non-handshake packet from unknown ip/port " +
                "({}:{}, expected {}:{}), ignoring".format(
                    host, port, self.source_ip, self.__source_port)
            )
            return False
        else:
            return True

    def _lock(self, info):
        host, port = info
        if self.source_ip or self.__source_port:
            if host != self.source_ip:
                log.error(
                    "Received handshake packet from unknown ip " +
                    "({}, expected {}), ignoring".format(host, self.source_ip)
                )
                return {'type': 'info', 'content': "unknown ip, ignoring"}
            elif self.__lock_port and port != self.__source_port:
                log.error(
                    "Received handshake packet from unknown port " +
                    "({}, expected {}), ignoring".format(
                        port, self.__source_port)
                )
                return {'type': 'info', 'content': "unknown port, ignoring"}

            else:  # correct or allowed ip:port
                log.info("Re-locking receipts to: {}:{}".format(host, port))
                self.source_ip = host
                self.__source_port = port
                return
        else:  # haven't yet locked
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

    def _process_next_packet(self, packet_id, info):
        abort_connection = functools.partial(self.abort_connection, info)
        self.__state.received(packet_id, abort_connection)

    def cleanup(self):
        if self.__expect_task.running:
            self.__expect_task.stop()

    def datagramReceived(self, data, info):
        # log.debug("Received {} from {}:{}".format(data, host, port))
        # Decode
        try:
            decoded = data.decode("ascii")
        except AttributeError:
            log.error(
                "Received none ascii-encoded data: {}, ignoring".format(data))
            return

        # Strip
        try:
            stripped = self._strip_padding(decoded)
        except ValueError:
            log.error(
                "Could not find delimiter: '{}'"
                " in received (padded?) packet: {}. Bad json?".format(
                    PADDING_DELIMITER, decoded))
            return

        # Process packet
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
            msg = self._lock(info)
            if msg:  # failed to lock
                return self._send_json(msg, info)
            msg = self._process_handshake(pps)
            self._send_json(msg)
            return

        # Other packets (not handshake) need to have their source verified
        else:
            if not self._verify(info):
                self._send_json(
                    {'type': 'info', 'content': "unknown ip/port, ignoring"},
                    info,
                )
                # Might want to abort or reset here
                return

        if packet_type == "next_packet":
            try:
                packet_id = int(data['packet_id'])
            except (KeyError, ValueError):
                log.error(
                    "Bad 'packet_id' key in handshake packet: {}".format(data))
                return
            self._process_next_packet(packet_id, info)

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
        if self._pending_reset_request:  # API waiting
            self._pending_reset_request.complete_reset_request()
        self._pending_reset_request = ResetRequest(request, self._send_json)

    @staticmethod
    def __expect_task_errback(reason):
        log.error("expect_packet() failed with:")
        print(reason.getTraceback())

    def abort_connection(self, info):
        msg = {'type': "abort"}
        self._send_json(msg, info)


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
