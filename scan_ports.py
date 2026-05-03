import socket

ip = "100.123.233.122"
ports = [8080, 8081, 11434, 3000]

print(f"Scanning ports on {ip}...")
for port in ports:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    result = s.connect_ex((ip, port))
    if result == 0:
        print(f"PORT {port} is OPEN!")
    else:
        print(f"PORT {port} is CLOSED.")
    s.close()
