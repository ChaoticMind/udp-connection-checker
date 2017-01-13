#!/usr/bin/env python3
import json
import argparse
import logging
from collections import OrderedDict

from twisted.internet import reactor, task
from twisted.internet.protocol import DatagramProtocol
from twisted.web import server, resource
from twisted.web.util import redirectTo
from prometheus_client import REGISTRY, generate_latest, CONTENT_TYPE_LATEST

MTU = 1316  # enforce that sent packets are not larger than this


# TODO:
# 	- Allow disconnections/reconnections without restarting both programs
# 		- server ctrl+c (with jitter?) looping call cancelled
# 		- permission denied on the client if a firewall rule is present
# 	- Use prometheus counters
# 	- For high thresholds, it seems that we don't register packet losses properly


# API stuff

class HttpApi(resource.Resource):
	"""Root resource"""
	def __init__(self, conn, logic):
		super(HttpApi, self).__init__()
		self.putChild(b"help", GenerateHelp())
		self.putChild(b"metrics", MetricsResource())
		self.putChild(b"status", Status(logic))
		self.putChild(b"reset", Reset(conn))

	def getChild(self, name, req):
		return self

	def render_GET(self, request):
		logging.debug('[HTTP API]: Received "/" request')
		return redirectTo(b"help", request)


class GenerateHelp(resource.Resource):
	"""Simple resource displaying possible api calls"""
	isLeaf = True

	def render_GET(self, request):
		logging.debug('[HTTP API]: Received "help" request')
		help_str = OrderedDict()
		help_str['/help'] = "Lists API calls (this message)"
		help_str['/metrics'] = "Lists metrics"
		help_str['/status'] = "Lists status"
		help_str['/reset'] = "Disconnects from client"
		request.responseHeaders.addRawHeader(b"content-type", b"application/json")
		return bytes("{}".format(json.dumps(help_str)), "utf-8")


class MetricsResource(resource.Resource):
	"""Twisted ``Resource`` that serves prometheus metrics."""
	isLeaf = True

	def __init__(self, registry=REGISTRY):
		self.registry = registry

	def render_GET(self, request):
		logging.debug('[HTTP API]: Received "metrics" request')
		request.setHeader(b'Content-Type', CONTENT_TYPE_LATEST.encode('ascii'))
		return generate_latest(self.registry)


class Status(resource.Resource):
	"""Human readable metric data"""
	isLeaf = True

	def __init__(self, logic):
		self.__logic = logic

	def render_GET(self, request):
		logging.debug('[HTTP API]: Received "status" request')
		request.responseHeaders.addRawHeader(b"content-type", b"application/json")
		return bytes(repr(self.__logic), 'utf-8')


class Reset(resource.Resource):
	"""Drop connection to the client, forcing a new handshake"""
	isLeaf = True

	def __init__(self, conn):
		self.__conn = conn

	def render_GET(self, request):
		logging.debug('[HTTP API]: Received "reset" request')
		if self.__conn._source_ip:
			self.__conn.reset_connection(request)
			return server.NOT_DONE_YET
		else:
			return b"Connection not yet initialized"


# UDP stuff

class Receiver(DatagramProtocol):
	def __init__(self, nolock, logic_handler):
		super().__init__()
		self.__initialized = False
		self._source_ip = None
		self.__source_port = None
		self.__lock_port = not nolock
		self.__logic = logic_handler
		self.__expect_task = task.LoopingCall(self.__logic.expect_packet)
		self.__reset_task = None
		self.__pending_reset = None

	def datagramReceived(self, data, info):
		# Step 1: lock/verify
		host, port = info
		# logging.debug("Received {} from {}:{}".format(data, host, port))
		if self._source_ip or self.__source_port:
			if host != self._source_ip:
				logging.error("Received packet from unknown ip ({}, expected {}), ignoring".format(host, self._source_ip))
				msg = {'type': 'info', 'content': "unknown ip, ignoring"}
				self._send_json(msg, info)
				return
			elif self.__lock_port and port != self.__source_port:
				logging.error("Received packet from unknown port ({}, expected {}), ignoring".format(port, self.__source_port))
				msg = {'type': 'info', 'content': "unknown port, ignoring"}
				self._send_json(msg, info)
				return
			else:  # correct ip:port
				pass
		else:
			logging.info("Locking receipts to: {}:{}".format(host, port))
			self._source_ip = host
			self.__source_port = port

		# Step 2: strip
		delimiter = bytes('}', 'ascii')[0]
		for i, x in enumerate(data):  # find padding delimiter
			if x == delimiter:
				break
		if i < len(data) - 1:
			stripped = len(data) - (i + 1)
			data = data[:i + 1]  # strip padding
			logging.debug("Received: {} ({} bytes stripped)".format(data, stripped))
		else:
			logging.debug("Received: {}".format(data))

		# Step 3: decode
		data = json.loads(data.decode("ascii"))
		if data['type'] == "handshake":
			if self.__initialized:
				logging.warning("Already shook hands, resetting state...")
				self.__expect_task.stop()
				self.__logic.reset_state()
				# return
			if self.__pending_reset:  # API waiting
				self.__pending_reset.write(b"Successfully resetted session")  # inform API
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
			self.__logic.received(data['packet_id'], self)
		else:
			logging.error("received unknown data: {}".format(data))

	def _send_json(self, data, info=None):
		encoded = bytes(json.dumps(data), "ascii")
		assert(len(encoded) <= MTU)
		if info is None:
			info = (self._source_ip, self.__source_port)
		logging.debug("Sending {}".format(encoded))
		self.transport.write(encoded, info)

	def reset_connection(self, request):
		msg = {'type': "reset"}
		self.__pending_reset = request
		self.__reset_task = task.LoopingCall(self._send_json, msg)
		self.__reset_task.start(1, now=True)

	def abort_connection(self):
		msg = {'type': "abort"}
		self._send_json(msg)


# main logic

class Logic():
	def __init__(self, threshold):
		self.__threshold = threshold
		self.reset_state()
		# self.__n_out_of_order = 0
		# self.__packet_losses = 0

	def reset_state(self):
		self.__expected_packet_id = 0
		self.__total_packets = 0
		self.__max_packet_id = 0
		self.__n_out_of_order = 0  # also reset
		self.__packet_losses = 0  # these two?

	def received(self, packet_id, conn):
		if packet_id > self.__expected_packet_id + self.__threshold:
			logging.info("[ERROR] Received a packet that's too far in the future. Something is wrong. Requesting abort from client and ignoring packet")
			# could possibly not do anything in this case
			conn.abort_connection()
			return

		if packet_id > self.__max_packet_id:
			logging.info("[Success] Received in-order packet {}".format(packet_id))
		self.__max_packet_id = max(self.__max_packet_id, packet_id)

		min_packet_id = self.__max_packet_id - self.__threshold
		if min_packet_id < packet_id < self.__max_packet_id:
			self.__n_out_of_order += 1
			logging.error("[Fail] Received out of order packet {}".format(packet_id))
		elif packet_id < min_packet_id:
			logging.error("[Fail] Received a very old packet. It is considered lost by now...")

		self.__total_packets += 1

	def expect_packet(self):
		logging.debug("Expecting packet: {}".format(self.__expected_packet_id))
		# Note: if we have a perf bottleneck, we could just call this less often
		# and calculate __expected_packet_id more cleverly
		self.__expected_packet_id += 1
		old_losses = self.__packet_losses
		new_losses = max(0, self.__expected_packet_id - self.__total_packets - self.__n_out_of_order - self.__threshold - 0)  # -0 because we start at 0

		if new_losses > old_losses:
			logging.error("[Fail] Most likely lost a packet for a total of: {}".format(new_losses))
			self.__packet_losses = new_losses
		elif new_losses < old_losses:
			# This means we eventually received packets either out of order or we thought we lost
			pass
			# logging.critical("Received a packet that we thought we lost? out of order? Shouldn't happen?")

	def __repr__(self):
		ret = OrderedDict()
		ret["Next expected packet id"] = self.__expected_packet_id
		ret["Highest received packet id"] = self.__max_packet_id
		ret["Total received packets"] = self.__total_packets
		ret["Number of out of order packets"] = self.__n_out_of_order
		ret["Number of packets lost"] = self.__packet_losses
		return json.dumps(ret)


def main():
	parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter, description='server for udp packet loss checker (start first)')
	parser.add_argument('-v', action='count', help="verbosity increases with each 'v' | critical/error/warning/info/debug", default=0)
	parser.add_argument('-p', '--http-port', default=8005, type=int, help="http port to listen on for metrics/api")
	parser.add_argument('-u', '--udp-port', default=9999, type=int, help="udp port to listen on for keep-alive packets")
	parser.add_argument('-t', '--threshold', default=2, type=int, help="number of packets received before we count a packet as either out of order or lost")
	parser.add_argument('-d', '--dont-lock-port', action='store_true', help="don't lock to receiving port (still locks to ip)")

	args = parser.parse_args()

	level = max(10, 50 - (10 * args.v))
	print('Logging level is: {}'.format(logging.getLevelName(level)))
	logging.basicConfig(format='%(asctime)s: %(levelname)s:\t%(message)s', level=level)

	l = Logic(args.threshold)
	conn = Receiver(args.dont_lock_port, l)

	site = server.Site(HttpApi(conn, l))
	reactor.listenTCP(args.http_port, site)
	reactor.listenUDP(args.udp_port, conn)
	reactor.run()


if __name__ == '__main__':
	main()
