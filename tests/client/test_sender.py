import logging
import json

from twisted.trial import unittest

from client.sender import Sender
from client import MTU

logger = logging.getLogger()
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)


class SenderFactory:
    @staticmethod
    def create():
        return Sender(
            jitter=0,
            src_port=8080,
            pad=None,
            dst_ip="localhost",
            dst_port=4242,
            pps=1,
        )


class TestReceivePacket(unittest.TestCase):
    def setUp(self):
        self.sender = SenderFactory.create()
        # self.clock = task.Clock()
        # self.sender.DEFAULT_CLOCK = self.clock
        logging.disable(logging.DEBUG)  # activate logging

    def tearDown(self):
        pass

    def receive_packet(self, msg):
        info = "localhost", 4242
        encoded = bytes(json.dumps(msg), "ascii")
        self.sender.datagramReceived(encoded, info)

    # tests
    def test_receive_bad_packet(self):
        data = {
            "type": "ack"
        }
        info = "localhost", 4242
        logging.disable(logging.ERROR)
        self.assertRaises(
            AttributeError, self.sender.datagramReceived, data, info)

    def test_receive_expected_ACK(self):
        data = {
            "type": "ack"
        }
        logging.disable(logging.ERROR)
        self.receive_packet(data)
        self.sender.cleanup()

    def test_receive_unexpected_remote(self):
        data = {
            "type": "something"
        }
        info = "localhost", 4243
        logging.disable(logging.ERROR)
        self.assertRaises(
            ValueError, self.sender.datagramReceived, data, info)


class TestReset(unittest.TestCase):
    def setUp(self):
        self.sender = SenderFactory.create()

    def tearDown(self):
        self.sender.cleanup()

    def test_unexpected_reset(self):
        self.assertFalse(self.sender.process_reset())
        self.assertEquals(self.sender._next_packet_id, 0)

    def test_expected_reset(self):
        self.sender.process_handshake_ack()
        self.assertTrue(self.sender.process_reset())
        self.assertEquals(self.sender._next_packet_id, 0)


class TestHandshake(unittest.TestCase):
    def setUp(self):
        self.sender = SenderFactory.create()
        logging.disable(logging.DEBUG)

    def tearDown(self):
        self.sender.cleanup()

    def test_receive_unexpected_ACK(self):
        logging.disable(logging.ERROR)
        self.assertTrue(self.sender.process_handshake_ack())
        self.assertFalse(self.sender.process_handshake_ack())

    def test_ack_after_unexpected_reset(self):
        logging.disable(logging.ERROR)
        self.assertFalse(self.sender.process_reset())
        self.assertTrue(self.sender.process_handshake_ack())

    def test_expected_ACK_after_reset(self):
        logging.disable(logging.ERROR)
        self.assertTrue(self.sender.process_handshake_ack())
        self.assertTrue(self.sender.process_reset())
        self.assertTrue(self.sender.process_handshake_ack())


class TestPadding(unittest.TestCase):
    def setUp(self):
        self.sender = SenderFactory.create()
        logging.disable(logging.DEBUG)

    def tearDown(self):
        self.sender.cleanup()

    # tests
    def test_padding(self):
        encoded = bytes("test", "ascii")
        self.assertLess(len(encoded), MTU)
        data = self.sender._pad_data(encoded)
        self.assertGreater(data, encoded)
        self.assertEquals(len(data), MTU)
