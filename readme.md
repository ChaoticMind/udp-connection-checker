# Description
`server.py` is a server that expects a constant stream of UDP packets
from a single endpoint. It provides statistics on:

- Number of packets received in-order
- Number of packets received out-of-order
- Number of dropped packets

It also provides an API endpoint for [Prometheus](https://prometheus.io/).

`client.py` simply sends a constant stream of UDP packets.


## Handshake
The first communication between the client and server is a handshake.
The client announces:

- The number of `packets_per_second` it will be sending.
- The number of packets received before we count a packet as either out
of order or lost. It's known as `threshold`.

Once communication between a client and a server is established, the
server will reject all packets received from a different client. Support
for multiple clients is currently outside the scope of this application.

## Internals
The server has a few counters which strictly increase:

- `total_packets` increments by one when a packet is received.
- `max_packet_id` indicates `max(max_packet_id, latest_packet_id)`.
 It's updated every time a packet is received.
- `out_of_order` increments by one when each packet is received with its
 id being `threshold < id < max_packet_id`
- `expected_max_packet_id` increments every second by `packets_per_second`
- `packet_losses` increments every second by
 `expected_max_packet_id - total_packets - out_of_order`

## Protocol

The client <--> server communicate with each other via ascii-encoded json.
The possible packets types are:

### Handshake

The client sends a handshake message consisting of:
```json
{
    'type': "handshake",
    'pps': <packets_per_second>,
}
```
The server replies with `{"type": "ack"}`
A handshake packet results in the server resetting its state (resetting
counters), and settings its expected packets per seconds to be received.
If applicable, receiving the handshake packet also informs HTTP API that
a reset has completed.

When the `ACK` is received by the client, the client starts sending UDP
packets. Note that the client keeps sending the handshake (once per
second) until it receives an `ACK`.

### Next Packet

Every period (inverse of `packets_per_second`), the client sends a new
packet:
```json
{
    'type': "next_packet",
    'timestamp': `now()`,
    'packet_id': <next_packet_id>,
}
```
The server compares the `packet_id` to its `expected_packet_id` and
appropriately adjusts its internal counters described in the "Internals"
section above.

The server doesn't reply to the client, since it tries to be stateless.

### Reset

The `reset` packet is triggered by the server's API (`/reset`) and
results in sending to the client, the payload: `{'type': "reset"}` This
resets the client's packet_id and will result in sending a new
handshake.

Note that the server keeps sending the `reset` packet (once per second)
until a new handshake is received.

### Abort

The `abort` packet consists of the payload: `{'type': "abort"}` and is
currently only sent to the client if the server receives a packet
unexpectedly far in the future, which should not be possible.

When the client receives this packet, it stops sending new packets.


### Info

The `info` packet is sent by the server, and usually simply indicates a
message that should be displayed by the client.

Currently, it's only
used when receiving a packet from an unknown ip/port:
`{'type': 'info', 'content': "unknown ip, ignoring"}`


# API
The server provides an API which exposes its internal counters (`/status`),
metrics (`/metrics`) as well as provide some control over its behavior
(`/reset`).

The `metrics` endpoint is specifically targetting prometheus, and is generated
via the [prometheus client](https://github.com/prometheus/client_python)


# TODO:

### Features

- Use prometheus counters
- For high thresholds, it seems that we don't register packet losses properly


### Write tests for:

- Allow disconnections/reconnections without restarting both programs
	- ctrl + c on client then up enter
	- ctrl + c on server then up enter (with and without jitter)
	- another client connects (with and without -d)
	- client starts before the server starts (with and without jitter)
	- client sends handshake that never gets ACKed (it should keep retrying)
- API reset (multiple resets with no ACKS, multiple ACKS, etc)
