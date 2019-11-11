#!/usr/bin/python3
import socket
import sys
import errno
import argparse
import os
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
    size_of_int = 4
    if len(sys.argv) < 2:
        print("The program should get port number")
    else:
        port = int(sys.argv[1])
        try:
            soc_serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            soc_serv.bind(('', port))
            soc_serv.listen(10)
            while True:  # to ask about the another while and
                (client_socket, address) = soc_serv.accept()
                len_of_rec_msg = struct.unpack(">i", client_socket.recv(size_of_int))[0]
                path = recvall(client_socket, len_of_rec_msg).decode()
                dir_info = os.popen("ls -l " + path).read()
                len_of_send_msg = struct.pack(">i", len(dir_info))
                client_socket.sendall(len_of_send_msg)
                client_socket.sendall(dir_info.encode())
                client_socket.close()
            soc_serv.close()
        except OSError as error:
            client_socket.close()
            soc_serv.close()
            if error.errno == errno.ECONNREFUSED:
                print("Connection refused")
            else:
                print(error.stderror)


if __name__ == "__main__":
    main()
