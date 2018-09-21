import logging
import json

from twisted.trial import unittest

from server.state import State
from server.receiver import Receiver
from tests import FunctionCalled, do_nothing


class ReceiverFactory:
    @staticmethod
    def create(nolock=False):
        threshold = 2
        state = State(threshold)

        return Receiver(
            nolock=nolock,
            state_handler=state,
        )


class MockRequest:
    def __new__(cls):
        cls.write = do_nothing
        cls.finish = do_nothing
        return cls


class TestVerifyOrLock(unittest.TestCase):
    def setUp(self):
        self.receiver = ReceiverFactory.create()
        logging.disable(logging.DEBUG)  # activate logging
        self.info = ("localhost", 4242)

    def tearDown(self):
        pass

    # tests
    def test_lock_state(self):
        logging.disable(logging.INFO)
        self.assertIsNone(self.receiver.source_ip)
        self.assertIsNone(self.receiver._lock(self.info))
        self.assertIsNotNone(self.receiver.source_ip)

    def test_lock_success(self):
        logging.disable(logging.INFO)
        self.assertIsNone(self.receiver._lock(self.info))
        self.assertIsNone(self.receiver._lock(self.info))

    def test_verify_unknown(self):
        self.assertEquals(self.receiver._verify(self.info), 1)

    def test_host_changed(self):
        logging.disable(logging.ERROR)
        self.assertIsNone(self.receiver._lock(self.info))
        self.assertEquals(self.receiver._verify(self.info), 0)
        self.assertEquals(self.receiver._verify(("other_host", 4242)), 2)

    def test_port_changed(self):
        logging.disable(logging.ERROR)
        self.assertIsNone(self.receiver._lock(self.info))
        self.assertEquals(self.receiver._verify(self.info), 0)
        self.assertEquals(self.receiver._verify(("localhost", 4444)), 2)
        self.receiver._process_handshake = FunctionCalled(
            self.receiver._process_handshake)

        payload = bytes(json.dumps({'type': "handshake", 'pps': 1}), "ascii")
        self.receiver.datagramReceived(payload, ("localhost", 4444))
        self.assertIsNotNone(self.receiver._lock(("localhost", 4444)))
        self.assertFalse(self.receiver._process_handshake.called)

    def test_port_changed_allowed(self):
        logging.disable(logging.ERROR)
        self.receiver = ReceiverFactory.create(nolock=True)
        self.assertIsNone(self.receiver._lock(self.info))
        self.assertIsNone(self.receiver._lock(("localhost", 4444)))


class TestStripPadding(unittest.TestCase):
    def setUp(self):
        self.receiver = ReceiverFactory.create()
        logging.disable(logging.DEBUG)  # activate logging

    def tearDown(self):
        pass

    # tests
    def test_strip_no_padding(self):
        decoded = json.dumps({"test": 42})
        stripped = self.receiver._strip_padding(decoded)
        self.assertEquals(stripped, decoded)

    def test_strip_padding(self):
        data = json.dumps({"test": 42})
        encoded = bytes(data, "ascii")
        padded = encoded + bytes("some padding", "ascii")
        decoded_padded = padded.decode("ascii")
        stripped = self.receiver._strip_padding(decoded_padded)
        self.assertLess(stripped, decoded_padded)
        self.assertEquals(stripped, data)


class TestDecode(unittest.TestCase):
    def setUp(self):
        self.receiver = ReceiverFactory.create()
        self.receiver._strip_padding = FunctionCalled(
            self.receiver._strip_padding)
        logging.disable(logging.DEBUG)  # activate logging

    def tearDown(self):
        pass

    def receive_packet(self, msg):
        info = "localhost", 4242
        self.receiver.datagramReceived(msg, info)

    # tests
    def test_bad_encode(self):
        logging.disable(logging.ERROR)
        self.receive_packet(json.dumps('hello'))
        self.assertFalse(self.receiver._strip_padding.called)

    def test_bad_json(self):
        logging.disable(logging.ERROR)
        self.receive_packet(bytes(json.dumps('hello'), 'ascii'))
        self.assertTrue(self.receiver._strip_padding.called)


class TestReceivedPacket(unittest.TestCase):
    def setUp(self):
        self.receiver = ReceiverFactory.create()
        logging.disable(logging.DEBUG)  # activate logging
        self.receiver._process_handshake = FunctionCalled(
            self.receiver._process_handshake)
        self.receiver._process_next_packet = FunctionCalled(
            self.receiver._process_next_packet)
        self.receiver._send_abort_request = FunctionCalled(
            self.receiver._send_abort_request)
        self.receiver._send_reset_request = FunctionCalled(
            self.receiver._send_reset_request)
        self.info = "127.0.0.1", 4242

    def tearDown(self):
        self.receiver.cleanup()

    def receive_packet(self, msg):
        encoded = bytes(json.dumps(msg), "ascii")
        self.receiver.datagramReceived(encoded, self.info)

    # tests
    def test_bad_type(self):
        logging.disable(logging.ERROR)
        self.receive_packet({})
        self.receive_packet([])

    def test_invalid_type(self):
        logging.disable(logging.ERROR)
        self.receive_packet({"type": 22})
        self.receive_packet({"type": "test"})

    def test_handshake_no_pps(self):
        logging.disable(logging.ERROR)
        self.assertFalse(self.receiver._process_handshake.called)
        self.receive_packet({"type": "handshake"})
        self.assertFalse(self.receiver._process_handshake.called)
        self.receive_packet({"type": "handshake", "pps": "1ss"})
        self.assertFalse(self.receiver._process_handshake.called)

    def test_handshake(self):
        logging.disable(logging.ERROR)
        self.assertFalse(self.receiver._process_handshake.called)
        self.receive_packet({"type": "handshake", "pps": 1})
        self.assertTrue(self.receiver._process_handshake.called)

    def test_two_handshakes(self):
        logging.disable(logging.ERROR)
        self.assertFalse(self.receiver._process_handshake.called)
        self.receive_packet({"type": "handshake", "pps": 1})
        self.receive_packet({"type": "handshake", "pps": 1})
        self.assertTrue(self.receiver._process_handshake.called)

    def test_handshake_waiting_API(self):
        logging.disable(logging.CRITICAL)
        self.assertIsNone(self.receiver._pending_reset_request)
        self.receiver.reset_connection(MockRequest())
        self.assertIsNotNone(self.receiver._pending_reset_request)
        self.receive_packet({"type": "handshake", "pps": 1})
        self.assertIsNone(self.receiver._pending_reset_request)

    def test_double_reset(self):
        logging.disable(logging.CRITICAL)
        self.assertIsNone(self.receiver._pending_reset_request)
        self.receiver.reset_connection(MockRequest())
        self.receiver.reset_connection(MockRequest())
        self.receive_packet({"type": "handshake", "pps": 1})

    def test_next_packet_no_id(self):
        logging.disable(logging.ERROR)
        self.assertFalse(self.receiver._process_next_packet.called)
        self.receive_packet({"type": "next_packet"})
        self.assertFalse(self.receiver._process_next_packet.called)
        self.receive_packet({"type": "next_packet", 'packet_id': "test"})
        self.assertFalse(self.receiver._process_next_packet.called)

    def test_next_packet_id(self):
        logging.disable(logging.ERROR)
        self.assertIsNone(self.receiver._lock(self.info))
        self.assertFalse(self.receiver._process_next_packet.called)
        self.receive_packet({"type": "next_packet", 'packet_id': 0})
        self.assertTrue(self.receiver._process_next_packet.called)

    def test_packet_id_no_handshake_reset(self):
        logging.disable(logging.ERROR)
        self.assertFalse(self.receiver._process_next_packet.called)
        self.assertFalse(self.receiver._send_reset_request.called)
        self.receive_packet({"type": "next_packet", 'packet_id': 1})
        self.assertFalse(self.receiver._process_next_packet.called)
        self.assertTrue(self.receiver._send_reset_request.called)

    def test_packet_id_no_handshake_abort(self):
        logging.disable(logging.ERROR)
        self.assertFalse(self.receiver._process_next_packet.called)
        self.assertFalse(self.receiver._send_abort_request.called)
        # lock to a different client (different ip/port)
        self.assertIsNone(self.receiver._lock(("localhost", 4444)))
        self.receive_packet({"type": "next_packet", 'packet_id': 1})
        self.assertFalse(self.receiver._process_next_packet.called)
        self.assertTrue(self.receiver._send_abort_request.called)
