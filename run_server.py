#!/usr/bin/env python3
import argparse
import logging

from twisted.internet import reactor
from twisted.web import server

from server.api import HttpApi
from server.receiver import Receiver
from server.main_loop import Logic


log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description='server for udp packet loss checker (start first)')
    parser.add_argument(
        '-v', action='count', default=0,
        help="verbosity increases with each 'v' |" +
        " critical/error/warning/info/debug")
    parser.add_argument(
        '-p', '--http-port', default=8005, type=int,
        help="http port to listen on for metrics/api")
    parser.add_argument(
        '-u', '--udp-port', default=9999, type=int,
        help="udp port to listen on for keep-alive packets")
    parser.add_argument(
        '-t', '--threshold', default=2, type=int,
        help="number of packets received before we count a packet as either" +
        "out-of-order or lost")
    parser.add_argument(
        '-d', '--dont-lock-port', action='store_true',
        help="don't lock to receiving port (still locks to ip)")

    args = parser.parse_args()

    # logging setup
    level = max(10, 50 - (10 * args.v))
    print('Logging level is: {}'.format(logging.getLevelName(level)))

    formatter = logging.Formatter(
        '%(asctime)s: %(levelname)s:\t%(message)s')
    #     '%(asctime)s: %(filename)s\t%(levelname)s:\t%(message)s')
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(sh)

    logger = logging.getLogger(__name__)
    logger.setLevel(level)

    logger = logging.getLogger('server')
    logger.setLevel(level)

    # main loop
    log.info("Starting main loop...")
    l = Logic(args.threshold)
    conn = Receiver(args.dont_lock_port, l)

    site = server.Site(HttpApi(conn, l))
    reactor.listenTCP(args.http_port, site)
    reactor.listenUDP(args.udp_port, conn)
    reactor.run()


if __name__ == '__main__':
    main()
