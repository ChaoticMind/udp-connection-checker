# Description
`server.py` is a server that expects a constant stream of UDP packets from one
endpoint. It provides statistics on:

- Number of packets received in-order
- Number of packets received out-of-order
- Number of dropped packets

It also provides an API endpoint for [Prometheus](https://prometheus.io/).

`client.py` simply sends the constant stream of UDP packets.


## Handshake
The first communication between the client and server is a handshake.
The client announces:

- The number of `packets_per_second` it will be sending.
- The number of packets received before we count a packet as either out of
order or lost. It's known as `threshold`.


## Internals
The server has a few counters which strictly increase:

- `total_packets` increments by one on each packet received.
- `max_packet_id` indicates `max(max_packet_id, current_packet.id)`.
It's updated every time a packet is received.
- `out_of_order` increments by one when each packet is received with its id
being `threshold < id < max_packet_id`
- `expected_max_packet_id` increments every second by `packets_per_second`
- `packet_losses` increments every second by
`expected_max_packet_id - total_packets - out_of_order`

# API
The server provides an API which exposes its internal counters (`/status`),
metrics (`/metrics`) as well as provide some control over its behavior
(`/reset`).

The `metrics` endpoint is specifically targetting prometheus, and is generated via the [prometheus client](https://github.com/prometheus/client_python)

# TODO:

### Features

- Allow disconnections/reconnections without restarting both programs
 - server ctrl+c (with jitter?) looping call cancelled
	- permission denied on the client if a firewall rule is present
- Use prometheus counters
- For high thresholds, it seems that we don't register packet losses properly


### Write tests for:

- Allow disconnections/reconnections without restarting both programs
	- ctrl + c on client then up enter
	- ctrl + c on server then up enter (with and without jitter)
	- another client connects (with and without -d)
	- another server instance starts
	- client starts before the server starts (with and without jitter)
	- client sends data without handshake
	- client sends handshake that never gets ACKed (it should keep retrying)
- API reset (multiple resets with no ACKS, multiple ACKS, etc)
