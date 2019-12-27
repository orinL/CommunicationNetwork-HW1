#!/usr/bin/python3
import socket
import sys
import struct
import errno
import random
import threading
from threading import Timer

# global variables and constants :
MAX_DATA_LEN = 512

# Packet opcodes
RRQ = "01"
WRQ = "02"
DATA = "03"
ACK = "04"
ERROR = "05"

# Possible errors:
FULL_DISK = "Disk is full"
ILLEGAL = "Illegal TFTP "
UNKNOWN_ID = "Unknown ID"

# Re-transmissions globals, set to default as previous exercise
timeout_in_seconds = 30
max_retransmission = 4
socket_dict = {}


# Input: list of parameters representing fields of packets
# Output: the encoded packet msg
def create_msg(msg_params):
    opcode = msg_params[0]
    msg_params = msg_params[1:]
    msg = b'0'
    if opcode == DATA:
        msg = struct.pack(f">hh{len(msg_params[1])}s", int(opcode), msg_params[0], msg_params[1].encode())
    elif opcode == ACK:
        msg = struct.pack(">hh", int(opcode), msg_params[0])
    elif opcode == ERROR:
        msg = struct.pack(f">hh{len(msg_params[1])}sb",
                          int(opcode), int(msg_params[0]), msg_params[1].encode(), 0)
    return msg


# Input: message parameters, address(=(host,address)), socket, re-transmit counter and a boolean
#        wait_for_ack which indicates whether we need to wait for ack
# Output: if we had to wait for an acknowledgement from the client
#         then the output is list of parameters of the ack message (which can be either ack or data)
# Notes: this method calls to wait_for_acknowledgement which handles the response from the client
def send_msg(msg_params, address, client_socket, retransmit_counter, wait_for_ack):
    # sending and acking message with re-transmission
    msg = create_msg(msg_params)
    # no need to select since we are in socket thread
    client_socket.sendto(msg, address)
    if wait_for_ack:
        # wait for an appropriate acknowledgement or timeout using timer thread
        t = threading.Timer(timeout_in_seconds, wait_for_acknowledgement,
                            kwargs={"client_socket": client_socket, "msg_waiting_for_ack_params": msg_params,
                                    "address": address})
        t.start()
        t.join()
        # if we didn't finish wait for ack
        if not socket_dict[client_socket][0] and retransmit_counter > 0:
            retransmit_counter -= 1
            send_msg(msg_params, client_socket, retransmit_counter - 1, wait_for_ack)
        elif retransmit_counter == 0:
            return None

        return socket_dict[client_socket][1]


# Input: socket, msg that wait for ack params, re-transmit counter, address
# Output: params list of ack/data message. or None
# Notes: perform the timeout and retransmit mechanism
# this function wait for acknowledgement on sent message
# if the timeout expired, we will retransmit
# after 3 retransmits, we fill finish the connection
# if we got packet, we check if it is the ack we expected to(ACK or DATA).
# if so, we will return it's params list.
# otherwise, we will ignore the packet and wait for another one.
# if connection is timeout, None will be returned.
def wait_for_acknowledgement(client_socket, msg_waiting_for_ack_params, address):
    socket_dict[client_socket][0] = False
    received_appropriate_packet = False
    try:
        packet_params = []
        while not received_appropriate_packet:
            # no need to select since we are in socket thread
            packet = client_socket.recvfrom(MAX_DATA_LEN * 2)
            if packet[1][1] != address[1]:
                error_handler(client_socket, packet[1], None, UNKNOWN_ID)
                continue
            else:
                packet_params = parser(packet[0])
                if msg_waiting_for_ack_params[0] == DATA:
                    if packet_params[0] == ACK and packet_params[1] == msg_waiting_for_ack_params[1]:
                        received_appropriate_packet = True
                    elif packet_params[0] == ERROR:
                        received_appropriate_packet = True
                    elif len(msg_waiting_for_ack_params[2]) <= MAX_DATA_LEN:
                        received_appropriate_packet = True
                    else:
                        continue
                elif msg_waiting_for_ack_params[0] == ACK:
                    if packet_params[0] == DATA or packet_params[0] == ERROR:
                        received_appropriate_packet = True
                    else:
                        continue
                else:  # which mean we got wrong packet type from the right port, therefore we will ignore it
                    continue
        socket_dict[client_socket][1] = packet_params
        socket_dict[client_socket][0] = True
    except OSError as os_err:
        print(os_err)
        client_socket.close()
        exit(1)


# Input: socket, msg params list, address
# Output: nothing
# Notes: we read packets and send acks until we get a
#        packet which its data is less than Max size(512)
def read(soc_serv, msg_params_list, addr):
    block_number = 0
    new_data_params = [DATA, "0", ""]
    try:
        f = open(msg_params_list[1], 'r')
    except OSError as err:
        print(err)
        error_handler(soc_serv, addr, err, RRQ)
        return
    try:
        got_to_eof = 0
        while got_to_eof == 0:
            block_number += 1
            data = f.read(MAX_DATA_LEN)
            if len(data) < MAX_DATA_LEN:
                got_to_eof = 1
            new_data_params[1] = block_number
            new_data_params[2] = data
            # checking for ack right params in send_msg
            new_msg_params = send_msg(new_data_params, addr, soc_serv, 0, True)
            if new_msg_params is None:
                print("Connection Timeouted")
                f.close()
                return
            elif new_msg_params[0] == ERROR:
                print("Error Code : " + new_msg_params[1] + " ,Error Message : " + new_msg_params[2])
                f.close()
                return
            else:  # which mean we got an ack on the data block we sent, and can continue
                continue
        f.close()
    except OSError as err:
        print(err)
        error_handler(soc_serv, addr, err, RRQ)


# Input: socket, address, msg params
# Output: nothing
# Notes: we send the client ack 0 that indicates we are able to receive data
#        then in each send_msg we send ack and wait for data from client.
#        until it is the last packet(smaller than max size) and then we don't
#        wait for ack and send_msg with wait_for_ack=False
def write(sock, address, msg_params):
    # 0 is block number
    ack_params = [ACK, 0]
    try:
        f = open(msg_params[1], 'a')
    except OSError as err:
        print(err)
        error_handler(sock, address, err, WRQ)
        return
    try:
        got_to_eof = 0
        new_msg_params = send_msg(ack_params, address, sock, 0, True)
        while got_to_eof == 0:
            if new_msg_params is None:
                print("Connection Timeouted")
                f.close()
                return
            elif new_msg_params[0] == ERROR:
                print("Error Code : " + new_msg_params[1] + " ,Error Message : " + new_msg_params[2])
                f.close()
                return
            else:  # means we got data block, according to send_msg
                data = new_msg_params[2]
                # block number
                ack_params[1] = new_msg_params[1]
                f.write(data)
                if len(data) < MAX_DATA_LEN:
                    send_msg(ack_params, address, sock, 0, False)
                    got_to_eof = 1
                else:
                    new_msg_params = send_msg(ack_params, address, sock, 0, True)
        f.close()
    except OSError as err:
        print(err)
        error_handler(sock, address, err, WRQ)


# Input: socket, address, error, mode
# Output: sends the relevant message to the client. Returns nothing
# Notes: messages according to protocol
def error_handler(sock, address, err, mode):
    if mode == UNKNOWN_ID:
        send_msg([ERROR, "05", "Unknown transfer ID"], address, sock, 0, False)
    elif mode == ILLEGAL:
        send_msg([ERROR, "04", "Illegal TFTP operation"], address, sock, 0, False)
    elif err.errno == errno.EDQUOT:
        send_msg([ERROR, "03", "Disk full or allocation exceeded"], address, sock, 0, False)
    elif err.errno == 13 and mode == WRQ:
        send_msg([ERROR, "06", "File already exists"], address, sock, 0, False)
    elif err.errno == 13 and mode == RRQ:
        send_msg([ERROR, "02", "Access violation"], address, sock, 0, False)
    elif err.errno == 2:
        send_msg([ERROR, "01", "File not found"], address, sock, 0, False)
    else:
        send_msg([ERROR, "00", "Not Defined"], address, sock, 0, False)


# Input: encoded message
# Outpus: decoded list of parameters (according to fields of packets in protocol)
def parser(msg):
    opcode = "0" + str(struct.unpack(">h", msg[:2])[0])
    msg = msg[2:]
    if opcode == RRQ or opcode == WRQ:
        return [opcode, msg[:msg.find(b'\x00')].decode(), "octet"]
    elif opcode == DATA:
        return [opcode, struct.unpack(">h", msg[:2])[0], msg[2:].decode()]
    elif opcode == ACK:
        return [opcode, struct.unpack(">h", msg[:2])[0]]
    else:
        return [opcode, msg[:2].decode(), msg[2:-1].decode()]


# Socket Thread
def handle_socket_req(client_socket, msg_params, address):
    if msg_params[0] == WRQ:
        write(client_socket, address, msg_params)
    elif msg_params[0] == RRQ:
        read(client_socket, msg_params, address)
    else:
        error_handler(client_socket, address, None, ILLEGAL)
    client_socket.close()


# Main
def main(port):
    socket_created = False
    client_socket_created = False

    try:
        if not (1 <= port <= 65535):
            raise ValueError
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        socket_created = True
        server_socket.bind(('', port))
        while True:
            server_socket.settimeout(None)
            first_packet = server_socket.recvfrom((MAX_DATA_LEN * 2))
            # creating new socket for communication with that client
            random_port = random.randint(0, 65535)  # this is the range of valid ports
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            socket_dict[client_socket][0] = False
            socket_dict[client_socket][1] = ""
            client_socket_created = True
            client_socket.bind(('', random_port))
            # analyzing which packet it is
            msg = first_packet[0]
            msg_params = parser(msg)
            threading.Thread(target=handle_socket_req, kwargs={"msg_params": msg_params,
                                                               "client_socket": client_socket,
                                                               "address": first_packet[1]})
        server_socket.close()
    except OSError as error:
        if socket_created:
            server_socket.close()
        if client_socket_created:
            client_socket.close()
        print(error)
    except KeyboardInterrupt:
        if socket_created:
            server_socket.close()
        if client_socket_created:
            client_socket.close()
        print("\nBye Bye")
        exit(0)
    except ValueError:
        print("Invalid port number, should be between 1 and 65535")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("The program should get port number, timeout in seconds, num of retransmissions")
    else:
        port = int(sys.argv[1])
        timeout_in_seconds = int(sys.argv[2])
        max_retransmission = int(sys.argv[2])
        main(port)
