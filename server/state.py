import logging
import json

from collections import OrderedDict

log = logging.getLogger(__name__)


class State:
    def __init__(self, threshold):
        """`threshold` is the number of packets received before we count a
        packet as dropped.

        """
        self.__threshold = threshold
        self.__expected_packet_id = 0
        self._n_in_order_packets = 0
        self._max_packet_id = -1
        self._n_out_of_order = 0
        self.__packet_losses = 0
        self._n_late_packets = 0

    def reset_state(self):
        self.__expected_packet_id = 0
        self._n_in_order_packets = 0
        self._max_packet_id = -1
        # also reset these three?
        self._n_out_of_order = 0
        self.__packet_losses = 0
        self._n_late_packets = 0

    def received(self, packet_id, abort_callback):
        if packet_id > self.__expected_packet_id:
            log.critical(
                "Received a packet that's too far in the future." +
                "Something is wrong. Requesting abort from client and " +
                "ignoring packet")
            # could possibly not do anything in this case
            abort_callback()
            return False

        if packet_id > self._max_packet_id:
            log.info("Received in-order packet {}".format(packet_id))
            self._n_in_order_packets += 1
            self._max_packet_id = packet_id
            return True

        min_packet_id = self._max_packet_id - self.__threshold

        if packet_id >= min_packet_id:
            self._n_out_of_order += 1
            log.warning("Received out of order packet {}".format(packet_id))

        else:
            log.error(
                "Received a very old packet. " +
                "It is considered lost by now...")
            self._n_late_packets += 1
        return False

    def expect_packet(self):
        """This is called with often, with a frequency of "packets per second".

        Note: if we have a perf bottleneck, we could call this method less
        frequently and calculate self.__expected_packet_id more cleverly

        """
        log.debug("Expecting packet: {}".format(self.__expected_packet_id))
        self.__expected_packet_id += 1

        old_losses = self.__packet_losses
        n_received_packets = self._n_in_order_packets + self._n_out_of_order
        new_losses = max(
            0,
            self.__expected_packet_id - n_received_packets - self.__threshold)

        if new_losses > old_losses:
            log.error(
                "Most likely lost a packet for a total of: {}".format(
                    new_losses))
            self.__packet_losses = new_losses
            return False

        elif new_losses < old_losses:
            # This means we eventually received packets either out of order or
            # we thought we lost
            pass
            # log.critical(
            #     "Received a packet that we thought we lost?" +
            #     "out of order? Shouldn't happen?")
        return True

    def __repr__(self):
        ret = OrderedDict()  # can use {} in python3.6+
        ret["Next expected packet id"] = self.__expected_packet_id
        ret["Highest received packet id"] = self._max_packet_id
        ret["Total received packets in-order"] = self._n_in_order_packets
        ret["Number of out of order packets"] = self._n_out_of_order
        ret["Number of packets lost"] = self.__packet_losses
        ret["Number of late packets eventually received"] = (
            self._n_late_packets)
        return json.dumps(ret)
