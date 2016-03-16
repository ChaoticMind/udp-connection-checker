#!/usr/bin/env python
from __future__ import absolute_import, unicode_literals, division, print_function
import json
import argparse
import logging
import random
import time

from twisted.internet import reactor, task
from twisted.internet.protocol import DatagramProtocol

MTU = 1500  # enforce that sent packets are not larger than this
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
		self.__task = task.LoopingCall(self.send_next)

	def startProtocol(self):
		host = self.__dst_ip
		port = self.__dst_port

		self.transport.connect(host, port)
		logging.info("We're going to send to {}:{}".format(host, port))

	def datagramReceived(self, data, info):
		host, port = info
		data = json.loads(data.decode("ascii"))
		if data['type'] == "ack":
			logging.info("Handshake confirmed.. starting to send data...")
			inv_pps = 1 / self.__pps
			self.__task.start(inv_pps, now=True)
		elif data['type'] == "reset":
			logging.info("Received reset request. Retriggering handshake...")
			self.__task.stop()
			self.__counter = 0
			self.send_handshake()
		elif data['type'] == "abort":
			logging.warning("Received 'abort' request, stopping task")
			self.__task.stop()
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
			reactor.callLater(jitter / 1000, self.transport.write, encoded)  # fake out of order packets
		else:
			try:
				self.transport.write(encoded)
			except AttributeError:
				# periodically retry handshake
				raise

	def send_handshake(self):
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


def positive_float(value):
	try:
		fvalue = float(value)
	except ValueError:
		raise argparse.ArgumentTypeError("invalid float value: {}".format(value))
	if fvalue < 0:
		raise argparse.ArgumentTypeError("must be > 0 (provided {})".format(fvalue))
	return fvalue


def main():
	parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter, description='client for udp packet loss checker')
	parser.add_argument('-v', action='count', help="verbosity increases with each 'v' | critical/error/warning/info/debug", default=0)
	parser.add_argument('-p', '--pps', default=5, type=positive_float, help="Packets per second to send")
	parser.add_argument('-j', '--jitter', type=positive_float, default=0, help="induce random jitter between 0 and JITTER [in ms]")
	parser.add_argument('-s', '--sending-port', default=12300, type=int, help="UDP port to send from (0 = different every time)")
	parser.add_argument('-di', '--dst-ip', default="127.0.0.1", type=str, help="Destination ip to send udp packets to.")
	parser.add_argument('-dp', '--dst-port', default=9999, type=int, help="Destination port to send udp packets to.")
	parser.add_argument('-d', '--dont-pad', action='store_true', help="don't pad packets to {}".format(MTU))

	args = parser.parse_args()

	level = max(10, 50 - (10 * args.v))
	print('Logging level is: {}'.format(logging.getLevelName(level)))
	logging.basicConfig(format='%(asctime)s: %(levelname)s:\t%(message)s', level=level)

	port = args.sending_port
	pps = args.pps
	pad = not args.dont_pad

	if pad:
		mbps = (pps * MTU) / 1024 / 1024
		logging.info(
			"Sending {} packet{} per second ({:.4f} MiB/s - {:.4f} MBit/s)".format(pps, 's' if not pps == 1 else '', mbps, mbps * 8))
	else:
		logging.info(
			"Sending {} packet{} per second".format(pps, 's' if not pps == 1 else ''))

	s = Sender(args.jitter, port, pad, args.dst_ip, args.dst_port, pps)

	reactor.listenUDP(port, s)
	s.send_handshake()
	reactor.run()


if __name__ == '__main__':
	main()
