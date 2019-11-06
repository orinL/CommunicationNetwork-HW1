#!/usr/bin/python3
import socket
import sys
import errno
import argparse
import os

def main():
    if len(sys.argv) < 2 :
        print("The program should get port number")
    else:
        port = int(sys.argv[1])
        try:
            soc_serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            soc_serv.bind(('', port))
            soc_serv.listen(10)
            while (True):  # to ask about the another while and
                (client_socket, address) = soc_serv.accept()
                path = ""
                read = 1;
                while read > 0 :
                    variable_bytes = client_socket.recv(2)
                    print ("is last?")
                    decoded =  variable_bytes.decode();
                    read = len(decoded)
                    path = path + decoded
                    print(path)
                    print("done iteraion")
                dir_info = os.listdir(path)  # to make to ls-l

                client_socket.sendall(('\n'.join(dir_info)).encode())
                client_socket.close()
            soc_serv.close()
        except OSError as error:
            client_socket.close()
            soc_serv.close()
            if error.errno == errno.ECONNREFUSED:
                print("Connection refused")
            else:
                print(error.stderror)


if __name__ == "__main__" :
    main()