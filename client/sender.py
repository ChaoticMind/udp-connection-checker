import json
import random
import time
import logging

from twisted.internet import reactor, task
from twisted.internet.protocol import DatagramProtocol

from client import MTU

log = logging.getLogger(__name__)


RANDOM_PADDING = [random.randint(0, 127) for x in range(MTU)]


class Sender(DatagramProtocol):
    _handshake_retry_period_s = 1

    def __init__(self, jitter, src_port, pad, dst_ip, dst_port, pps):
        super().__init__()
        self._next_packet_id = 0
        self.__jitter = jitter
        self.__pad = pad
        self.__port = src_port
        self.__dst_ip = dst_ip
        self.__dst_port = dst_port
        self.__pps = pps
        self.__send_task = task.LoopingCall(self.send_next)

        self.__handshake_task = task.LoopingCall(self.__send_handshake)
        d = self.__handshake_task.start(
            self._handshake_retry_period_s, now=False)
        d.addErrback(self.__send_handshake_errback)

    def startProtocol(self):
        host = self.__dst_ip
        port = self.__dst_port

        # self.transport.connect(host, port)
        log.info("We're going to send to {}:{}".format(host, port))

    def stopProtocol(self):
        # reactor.listenUDP(self.__port, self)  # reconnect
        pass

    def datagramReceived(self, data, info):
        host, port = info
        if host != self.__dst_ip or port != self.__dst_port:
            self.cleanup()
            raise ValueError(
                "received packet from invalid host/port: "
                "{}:{}".format(host, port) +
                " - expected {}:{}".format(self.__dst_ip, self.__dst_port))

        try:
            data = json.loads(data.decode("ascii"))
        except AttributeError as e:
            log.error("Couldn't decode packet")
            self.cleanup()
            raise e

        if data['type'] == "ack":
            self.process_handshake_ack()

        elif data['type'] == "reset":
            self.process_reset()

        elif data['type'] == "abort":
            log.warning("Received 'abort' request, stopping task")
            self.__send_task.stop()

        elif data['type'] == "info":
            log.warning("received message: {}".format(data['content']))

        else:
            log.error("received unknown data: {}".format(data))

    def process_handshake_ack(self):
        log.info("Handshake confirmed.. starting to send data...")
        inv_pps = 1 / self.__pps

        if self.__handshake_task.running:
            self.__handshake_task.stop()
            d = self.__send_task.start(inv_pps, now=True)
            d.addErrback(self.__send_next_errback)
            return True
        return False

    def process_reset(self):
        self._next_packet_id = 0

        if not self.__handshake_task.running:
            log.info("Received reset request. Retriggering handshake...")
            self.__send_task.stop()
            d = self.__handshake_task.start(
                self._handshake_retry_period_s, now=True)
            d.addErrback(self.__send_handshake_errback)
            return True

        else:
            assert(self.__send_task.running is False)
            log.warning(
                "Received reset request while a handshake was pending..."
                ", ignoring...")
            return False

    def _send_json(self, data, pad):
        encoded = bytes(json.dumps(data), "ascii")
        to_pad = MTU - len(encoded)
        assert(to_pad >= 0)
        if pad:
            log.debug(
                "Sending {} (+ {} bytes padding)".format(encoded, to_pad))
            # padding = [random.randint(0, 127) for x in range(to_pad)]
            padding = RANDOM_PADDING[:to_pad]
            # not having the padding be different every time results in about
            # ~ 6x less cpu usage
            encoded += bytes(padding)
            assert(len(encoded) <= MTU)
        else:
            log.debug("Sending {}".format(encoded))

        info = (self.__dst_ip, self.__dst_port)
        if self.__jitter:
            jitter_s = random.randint(0, self.__jitter) / 1000
            # jitter helps simulate fake out-of-order packets
            reactor.callLater(jitter_s, self.transport.write, encoded, info)
        else:
            try:
                self.transport.write(encoded, info)
            except AttributeError:
                # self.transport.connect(self.__dst_ip, self.__dst_port)
                log.warning("Could not send data...")

    def __send_handshake(self):
        data = {
            'type': "handshake",
            'padding': self.__pad,  # unused
            'mtu': MTU,  # unused
            'port': self.__port,  # unused
            'pps': self.__pps,
        }
        log.info("sending handshake")
        self._send_json(data, pad=False)

    @staticmethod
    def __send_handshake_errback(reason):
        log.error("send_handshake() failed with:")
        print(reason.getTraceback())

    def send_next(self):
        data = {
            'type': "next_packet",
            'timestamp': time.time(),
            'packet_id': self._next_packet_id,
        }
        self._send_json(data, pad=self.__pad)
        self._next_packet_id += 1

    @staticmethod
    def __send_next_errback(reason):
        log.error("send_next() failed with:")
        print(reason.getTraceback())

    def cleanup(self):
        if self.__handshake_task.running:
            self.__handshake_task.stop()

        if self.__send_task.running:
            self.__send_task.stop()
