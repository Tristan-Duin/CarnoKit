"""Quick RCON diagnostic — run this standalone to test the connection."""
import socket
import struct
import sys

HOST = "127.0.0.1"
PORT = 27020
PASSWORD = "adminpass123"
TIMEOUT = 5.0

def encode(req_id, pkt_type, body=""):
    body_bytes = body.encode("utf-8")
    payload = struct.pack("<ii", req_id, pkt_type) + body_bytes + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload

def recv_packet(sock):
    size_data = sock.recv(4)
    if not size_data:
        return None
    size = struct.unpack("<i", size_data)[0]
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    req_id, pkt_type = struct.unpack("<ii", data[:8])
    body = data[8:-2].decode("utf-8", errors="replace")
    return req_id, pkt_type, body

print(f"[1] Connecting to {HOST}:{PORT} ...")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(TIMEOUT)
try:
    sock.connect((HOST, PORT))
    print("[1] TCP connected OK")
except Exception as e:
    print(f"[1] FAIL: {e}")
    sys.exit(1)

print(f"[2] Sending AUTH with password '{PASSWORD}' ...")
sock.sendall(encode(1, 3, PASSWORD))  # type 3 = AUTH

print("[3] Reading auth responses ...")
for i in range(5):
    try:
        pkt = recv_packet(sock)
        if pkt is None:
            print(f"  Response {i+1}: None (connection closed)")
            break
        req_id, pkt_type, body = pkt
        print(f"  Response {i+1}: id={req_id}  type={pkt_type}  body='{body[:80]}'")
        if req_id == -1:
            print("  >>> AUTH REJECTED (id=-1)")
            break
        if req_id == 1 and pkt_type == 2:
            print("  >>> AUTH SUCCESS")
            break
    except socket.timeout:
        print(f"  Response {i+1}: (timeout)")
        break

print()
print("[4] Sending ListPlayers ...")
sock.sendall(encode(2, 2, "ListPlayers"))  # type 2 = EXEC

print("[5] Reading command response ...")
for i in range(5):
    try:
        pkt = recv_packet(sock)
        if pkt is None:
            print(f"  Response {i+1}: None")
            break
        req_id, pkt_type, body = pkt
        print(f"  Response {i+1}: id={req_id}  type={pkt_type}  body='{body[:200]}'")
    except socket.timeout:
        print(f"  Response {i+1}: (timeout)")
        break

sock.close()
print("\n[Done]")
