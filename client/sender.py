import json
import random
import time
import logging

from twisted.internet import reactor, task
from twisted.internet.protocol import DatagramProtocol

from client import MTU

RANDOM_PADDING = [random.randint(0, 127) for x in range(MTU)]


class Sender(DatagramProtocol):
    def __init__(self, jitter, s_port, pad, ip, port, pps):
        super().__init__()
        self.__counter = 0
        self.__jitter = jitter
        self.__pad = pad
        self.__port = s_port
        self.__dst_ip = ip
        self.__dst_port = port
        self.__pps = pps
        self.__send_task = task.LoopingCall(self.send_next)
        self.__handshake_task = task.LoopingCall(self.__send_handshake)
        self.__handshake_task.start(1, now=False)

    def startProtocol(self):
        host = self.__dst_ip
        port = self.__dst_port

        # self.transport.connect(host, port)
        logging.info("We're going to send to {}:{}".format(host, port))

    def stopProtocol(self):
        # reactor.listenUDP(self.__port, self)  # reconnect
        pass

    def datagramReceived(self, data, info):
        host, port = info
        data = json.loads(data.decode("ascii"))
        if data['type'] == "ack":
            logging.info("Handshake confirmed.. starting to send data...")
            inv_pps = 1 / self.__pps
            if self.__handshake_task.running:
                self.__handshake_task.stop()
            self.__send_task.start(inv_pps, now=True)
        elif data['type'] == "reset":
            logging.info("Received reset request. Retriggering handshake...")
            if self.__send_task.running:
                self.__send_task.stop()
            self.__counter = 0
            self.__handshake_task.start(1, now=True)
        elif data['type'] == "abort":
            logging.warning("Received 'abort' request, stopping task")
            self.__send_task.stop()
        elif data['type'] == "info":
            logging.warning("received message: {}".format(data['content']))
        else:
            logging.error("received unknown data: {}".format(data))

    def _send_json(self, data, pad):
        encoded = bytes(json.dumps(data), "ascii")
        to_pad = MTU - len(encoded)
        assert(to_pad >= 0)
        if pad:
            logging.debug("Sending {} (+ {} bytes padding)".format(encoded, to_pad))
            # padding = [random.randint(0, 127) for x in range(to_pad)]
            padding = RANDOM_PADDING[:to_pad]  # doesn't need to be different every time (~ 6x less cpu usage)
            encoded += bytes(padding)
            assert(len(encoded) <= MTU)
        else:
            logging.debug("Sending {}".format(encoded))

        if self.__jitter:
            jitter = random.randint(0, self.__jitter)
            info = (self.__dst_ip, self.__dst_port)
            reactor.callLater(jitter / 1000, self.transport.write, encoded, info)  # fake out of order packets
        else:
            try:
                info = (self.__dst_ip, self.__dst_port)
                self.transport.write(encoded, info)
            except AttributeError:
                # self.transport.connect(self.__dst_ip, self.__dst_port)
                logging.warning("Could not send data...")

    def __send_handshake(self):
        data = {}
        data['type'] = "handshake"
        data['padding'] = self.__pad  # unused
        data['mtu'] = MTU  # unused
        data['port'] = self.__port  # unused
        data['pps'] = self.__pps
        logging.info("sending handshake")
        self._send_json(data, pad=False)

    def send_next(self):
        data = {}
        data['type'] = "next_packet"
        data['timestamp'] = time.time()
        data['packet_id'] = self.__counter
        self._send_json(data, pad=self.__pad)

        self.__counter += 1
