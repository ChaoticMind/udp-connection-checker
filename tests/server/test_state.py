import logging

from twisted.trial import unittest

from server.state import State
from server.receiver import Receiver
from tests import FunctionCalled, do_nothing

logger = logging.getLogger()
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)


class TestStateExpectPacket(unittest.TestCase):
    def setUp(self):
        self.threshold = 2
        self.state = State(threshold=self.threshold)
        self.conn = Receiver(nolock=True, state_handler=self.state)
        self.conn.abort_connection = FunctionCalled(do_nothing)
        # logging.disable(logging.DEBUG)  # activate logging

    def tearDown(self):
        pass

    # tests
    def test_expect_packet_same_losses(self):
        for n in range(self.threshold):
            self.assertTrue(self.state.expect_packet())
        self.state.received(0, do_nothing())
        self.assertTrue(self.state.expect_packet())

    def test_expect_packet_increase_losses(self):
        for n in range(self.threshold):
            self.assertTrue(self.state.expect_packet())
        logging.disable(logging.ERROR)
        self.assertFalse(self.state.expect_packet())

    def test_expect_decrease_losses(self):
        for n in range(self.threshold):
            self.assertTrue(self.state.expect_packet())
        logging.disable(logging.WARNING)
        self.state.received(0, do_nothing())
        self.state.received(0, do_nothing())
        self.assertTrue(self.state.expect_packet())


class TestStateReceived(unittest.TestCase):
    def setUp(self):
        self.threshold = 2
        self.state = State(threshold=self.threshold)
        self.conn = Receiver(nolock=True, state_handler=self.state)
        self.conn.abort_connection = FunctionCalled(do_nothing)
        logging.disable(logging.DEBUG)  # activate logging

    def tearDown(self):
        pass

    # tests
    def tests_received_in_order_packet(self):
        old_n_in_order = self.state._n_in_order_packets
        old_n_out_of_order = self.state._n_out_of_order
        logging.disable(logging.INFO)
        self.assertTrue(self.state.received(0, do_nothing()))
        self.assertFalse(self.conn.abort_connection.called)
        self.assertEquals(self.state._max_packet_id, 0)
        self.assertEquals(self.state._n_in_order_packets, old_n_in_order + 1)
        self.assertEquals(self.state._n_out_of_order, old_n_out_of_order)

    def tests_received_future_packet(self):
        logging.disable(logging.CRITICAL)
        self.state.received(0, do_nothing())
        old_max_id = self.state._max_packet_id
        old_n_in_order = self.state._n_in_order_packets
        old_n_out_of_order = self.state._n_out_of_order
        self.assertFalse(self.conn.abort_connection.called)
        self.assertFalse(self.state.received(9, self.conn.abort_connection))
        self.assertTrue(self.conn.abort_connection.called)
        self.assertEquals(self.state._max_packet_id, old_max_id)
        self.assertEquals(self.state._n_in_order_packets, old_n_in_order)
        self.assertEquals(self.state._n_out_of_order, old_n_out_of_order)

    def tests_received_out_of_order_packet(self):
        logging.disable(logging.INFO)
        self.state.received(0, do_nothing())
        old_max_id = self.state._max_packet_id
        old_n_in_order = self.state._n_in_order_packets
        old_n_out_of_order = self.state._n_out_of_order
        old_n_late_packets = self.state._n_late_packets
        logging.disable(logging.ERROR)
        self.assertFalse(self.state.received(0, do_nothing()))
        self.assertEquals(self.state._max_packet_id, old_max_id)
        self.assertEquals(self.state._n_in_order_packets, old_n_in_order)
        self.assertEquals(self.state._n_out_of_order, old_n_out_of_order + 1)
        self.assertEquals(self.state._n_late_packets, old_n_late_packets)

    def tests_received_first_packet(self):
        logging.disable(logging.INFO)
        self.assertTrue(self.state.received(0, do_nothing()))
        self.assertEquals(self.state._n_in_order_packets, 1)

    def tests_received_very_old_packet(self):
        logging.disable(logging.INFO)
        for n in range(10):
            self.assertTrue(self.state.expect_packet())
            self.state.received(n, do_nothing())
        old_max_id = self.state._max_packet_id
        old_n_in_order = self.state._n_in_order_packets
        old_n_out_of_order = self.state._n_out_of_order
        old_n_late_packets = self.state._n_late_packets
        logging.disable(logging.ERROR)
        self.assertFalse(self.state.received(1, do_nothing()))
        self.assertEquals(self.state._max_packet_id, old_max_id)
        self.assertEquals(self.state._n_in_order_packets, old_n_in_order)
        self.assertEquals(self.state._n_out_of_order, old_n_out_of_order)
        self.assertEquals(self.state._n_late_packets, old_n_late_packets + 1)
