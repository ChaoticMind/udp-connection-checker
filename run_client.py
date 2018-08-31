#!/usr/bin/env python3
import argparse
import logging

from twisted.internet import reactor

from client import MTU
from client.sender import Sender


def positive_float(value):
    try:
        fvalue = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "invalid float value: {}".format(value))

    if fvalue < 0:
        raise argparse.ArgumentTypeError(
            "must be > 0 (provided {})".format(fvalue))
    return fvalue


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description='client for udp packet loss checker')
    parser.add_argument(
        '-v', action='count', default=0,
        help="verbosity increases with each 'v' |" +
        " critical/error/warning/info/debug")
    parser.add_argument(
        '-p', '--pps', default=5, type=positive_float,
        help="Packets per second to send")
    parser.add_argument(
        '-j', '--jitter', type=positive_float, default=0,
        help="induce random jitter between 0 and JITTER [in ms]")
    parser.add_argument(
        '-s', '--sending-port', default=12300, type=int,
        help="UDP port to send from (0 = different every time)")
    parser.add_argument(
        '-di', '--dst-ip', default="127.0.0.1", type=str,
        help="Destination ip to send udp packets to.")
    parser.add_argument(
        '-dp', '--dst-port', default=9999, type=int,
        help="Destination port to send udp packets to.")
    parser.add_argument(
        '-d', '--dont-pad', action='store_true',
        help="don't pad packets to {}".format(MTU))

    args = parser.parse_args()

    level = max(10, 50 - (10 * args.v))
    print('Logging level is: {}'.format(logging.getLevelName(level)))
    logging.basicConfig(
        format='%(asctime)s: %(levelname)s:\t%(message)s', level=level)

    port = args.sending_port
    pps = args.pps
    pad = not args.dont_pad

    if pad:
        mbps = (pps * MTU) / 1024 / 1024
        logging.info(
            "Sending {} packet{} per second ".format(
                pps, 's' if not pps == 1 else '') +
            "({:.4f} MiB/s - {:.4f} MBit/s)".format(mbps, mbps * 8))
    else:
        logging.info(
            "Sending {} packet{} per second".format(
                pps, 's' if not pps == 1 else ''))

    s = Sender(args.jitter, port, pad, args.dst_ip, args.dst_port, pps)

    reactor.listenUDP(port, s)
    reactor.run()


if __name__ == '__main__':
    main()
