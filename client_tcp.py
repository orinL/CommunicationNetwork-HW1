#!/usr/bin/python3
import socket
import sys
import errno
import struct


def recvall(sock, n):
    # Helper function to recv n bytes or return None if EOF is hit
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data


def main(ip, port, dir_path):
    init_sock = False
    try:
        soc_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        init_sock = True
        soc_client.connect((ip, port))
        size_of_msg = struct.pack(">I", len(dir_path))
        soc_client.sendall(size_of_msg)
        soc_client.sendall(dir_path.encode())
        data_rec = recvall(soc_client, 4)
        len_of_rec_msg = struct.unpack(">I", data_rec)[0]
        data = recvall(soc_client, len_of_rec_msg)
        print(data.decode(), end="")
        soc_client.close()
    except OSError as error:
        if error.errno == errno.ECONNREFUSED:
            print("Connection refused")
        else:
            print(error)
        if init_sock:
            soc_client.close()
    except KeyboardInterrupt:
        if init_sock:
            soc_client.close()
        print("\nBye Bye")
        exit(0)


if __name__ == "__main__":
    if len(sys.argv) == 4:
        main(sys.argv[1], int(sys.argv[2]), sys.argv[3])
    else:
        print("The program should get ip, port number and directory path")
