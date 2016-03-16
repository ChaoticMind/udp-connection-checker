TODO: Write tests for:

- Allow disconnections/reconnections without restarting both programs
	- ctrl + c on client then up enter
	- ctrl + c on server then up enter (with and without jitter)
	- another client connects (with and without -d)
	- another server instance starts
	- client starts before the server starts (with and without jitter)
	- client sends data without handshake
	- client sends handshake that never gets acked (it should keep retrying)
- API reset (multiple resets with no acks, multiple acks, etc)
