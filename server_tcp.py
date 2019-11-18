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


def main(port):
    size_of_int = 4
    server_sock_init = False
    try:
        if not(1 <= port <= 65535):
            raise ValueError
        soc_serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock_init = True
        socket_init = False
        soc_serv.bind(('', port))
        soc_serv.listen(10)
        while True:  
            socket_init = False
            (client_socket, address) = soc_serv.accept()
            socket_init = True
            len_of_rec_msg = struct.unpack(">i", client_socket.recv(size_of_int))[0]
            path = recvall(client_socket, len_of_rec_msg).decode()
            dir_info = os.popen("ls -l " + path).read()
            len_of_send_msg = struct.pack(">i", len(dir_info))
            client_socket.sendall(len_of_send_msg)
            client_socket.sendall(dir_info.encode())
            client_socket.close()
        soc_serv.close()
    except OSError as error:
        if socket_init:
            client_socket.close()
        if server_sock_init:
            soc_serv.close()
        if error.errno == errno.ECONNREFUSED:
            print("Connection refused")
        else:
            print(error)
    except KeyboardInterrupt:
        if socket_init:
            client_socket.close()
        if server_sock_init:
            soc_serv.close()
        print("\nBye Bye")
        exit(0)
    except ValueError:
        print("Invalid port number, should be between 1 and 65535")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("The program should get port number")
    else:
        main(int(sys.argv[1]))
