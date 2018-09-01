import logging
import json

from collections import OrderedDict

log = logging.getLogger(__name__)


class State:
    def __init__(self, threshold):
        self.__threshold = threshold
        self.__expected_packet_id = 0
        self.__total_packets = 0
        self.__max_packet_id = 0
        self.__n_out_of_order = 0
        self.__packet_losses = 0
        # self.reset_state()

    def reset_state(self):
        self.__expected_packet_id = 0
        self.__total_packets = 0
        self.__max_packet_id = 0
        self.__n_out_of_order = 0  # also reset
        self.__packet_losses = 0  # these two?

    def received(self, packet_id, conn):
        if packet_id > self.__expected_packet_id + self.__threshold:
            log.info(
                "[ERROR] Received a packet that's too far in the future." +
                "Something is wrong. Requesting abort from client and " +
                "ignoring packet")
            # could possibly not do anything in this case
            conn.abort_connection()
            return

        if packet_id > self.__max_packet_id:
            log.info(
                "[Success] Received in-order packet {}".format(packet_id))
        self.__max_packet_id = max(self.__max_packet_id, packet_id)

        min_packet_id = self.__max_packet_id - self.__threshold
        if min_packet_id < packet_id < self.__max_packet_id:
            self.__n_out_of_order += 1
            log.error(
                "[Fail] Received out of order packet {}".format(packet_id))
        elif packet_id < min_packet_id:
            log.error(
                "[Fail] Received a very old packet. " +
                "It is considered lost by now...")

        self.__total_packets += 1

    def expect_packet(self):
        """This is called with often, with a frequency of "packets per second".

        Note: if we have a perf bottleneck, we could call this method less
        frequently and calculate self.__expected_packet_id more cleverly

        """
        log.debug("Expecting packet: {}".format(self.__expected_packet_id))
        self.__expected_packet_id += 1
        old_losses = self.__packet_losses
        new_losses = max(
            0,
            (self.__expected_packet_id - self.__total_packets -
                self.__n_out_of_order - self.__threshold - 0)
        )  # -0 because we start at 0

        if new_losses > old_losses:
            log.error(
                "[Fail] Most likely lost a packet for a total of: {}".format(
                    new_losses))
            self.__packet_losses = new_losses

        elif new_losses < old_losses:
            # This means we eventually received packets either out of order or
            # we thought we lost
            pass
            # log.critical(
            #     "Received a packet that we thought we lost?" +
            #     "out of order? Shouldn't happen?")

    def __repr__(self):
        ret = OrderedDict()  # can use {} in python3.6+
        ret["Next expected packet id"] = self.__expected_packet_id
        ret["Highest received packet id"] = self.__max_packet_id
        ret["Total received packets"] = self.__total_packets
        ret["Number of out of order packets"] = self.__n_out_of_order
        ret["Number of packets lost"] = self.__packet_losses
        return json.dumps(ret)
