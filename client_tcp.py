#!/usr/bin/python3
import socket
import sys
import errno
import argparse

def main():
    if len(sys.argv) < 4 :
        print("The program should get ip,port number , and directory path")
    else:
        ip = sys.argv[1]
        port = sys.argv[2]
        dir_path = sys.argv[3]
        try:
            soc_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            soc_client.connect((ip,int(port)))
            soc_client.sendall(dir_path.encode())
            variable_bytes = soc_client.recv(1024)
            print(variable_bytes.decode())
            soc_client.close()
        except OSError as error:
            if error.errno == errno.ECONNREFUSED:
                print("Connection refused")
            else:
                print(error.stderror)
            soc_client.close()


if __name__ == "__main__" :
    main()