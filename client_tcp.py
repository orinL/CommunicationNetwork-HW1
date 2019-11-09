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


def main():
    if len(sys.argv) < 4:
        print("The program should get ip,port number , and directory path")
    else:
        ip = sys.argv[1]
        port = sys.argv[2]
        dir_path = sys.argv[3]
        try:
            soc_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            soc_client.connect((ip, int(port)))
            data = struct.pack(">i", len(dir_path))
            soc_client.sendall(data)
            soc_client.sendall(dir_path.encode())
            len_of_rec_msg = struct.unpack(">i", soc_client.recv(4))[0]
            data = recvall(soc_client, len_of_rec_msg)
            print(data.decode())
            soc_client.close()
        except OSError as error:
            if error.errno == errno.ECONNREFUSED:
                print("Connection refused")
            else:
                print(error.stderror)
            soc_client.close()


if __name__ == "__main__":
    main()
