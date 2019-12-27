#!/usr/bin/python3
import socket
import sys
import struct
import errno
import random
import threading
from threading import Timer
from select import select

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

# Global dictionary and lists
socket_dict = {}
socket_to_recv_list = []
socket_to_send_list = []


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


#
# def update_recv_dict_socket(sock):
#     values = socket_to_send_dict[sock]
#     # add/update sock in recv dict
#     socket_to_recv_list.append(sock)
#     # socket_to_recv_dict[sock] = (file_path, block_number)
#     if values[0] == RRQ:


def update_before_send_dict():
    for sock, values in socket_dict:
        if sock in socket_to_send_list:
            if values[0] == RRQ:
                try:
                    f = open(values[1], 'r')
                except OSError as err:
                    print(err)
                    values[2] = error_handler(sock, values[4], err, RRQ)
                    return
                if sock in list(socket_dict.keys()):
                    values[5] = socket_dict[sock][1] + 1
                    values[3] += MAX_DATA_LEN
                # move to offset according to what we already read
                f.seek(values[3])
                data = f.read(MAX_DATA_LEN)
                if len(data) < MAX_DATA_LEN:
                    values[6] = True
                # update block number
                new_data_params = [DATA, str(values[5]), data]
                packed_msg = create_msg(new_data_params)
                values[2] = packed_msg
                f.close()
            elif values[0] == WRQ:
                # values[5] is block number
                ack_params = [ACK, values[5]]
                try:
                    f = open(values[1], 'a')
                except OSError as err:
                    print(err)
                    values[2] = error_handler(sock, values[4], err, WRQ)
                    return
                # if we already recv data we need to match block number
                if sock in list(socket_dict.keys()):
                    values[5] = socket_dict[sock][1]
                # if we are not sending first ack param
                if values[5] > 0:
                    if values[7] is not None:
                        f.write(values[7])
                    if len(values[7]) < MAX_DATA_LEN:
                        values[6] = True
                    f.close()
                values[2] = create_msg(ack_params)
            else:
                values[2] = error_handler(sock, values[4], None, ILLEGAL)


# Input: socket, address, error, mode
# Output: creates the relevant message to the client. Returns packed msg
# Notes: messages according to protocol
def error_handler(sock, address, err, mode):
    if mode == UNKNOWN_ID:
        return create_msg([ERROR, "05", "Unknown transfer ID"])
    elif mode == ILLEGAL:
        return create_msg([ERROR, "04", "Illegal TFTP operation"])
    elif err.errno == errno.EDQUOT:
        return create_msg([ERROR, "03", "Disk full or allocation exceeded"])
    elif err.errno == 13 and mode == WRQ:
        return create_msg([ERROR, "06", "File already exists"])
    elif err.errno == 13 and mode == RRQ:
        return create_msg([ERROR, "02", "Access violation"])
    elif err.errno == 2:
        return create_msg([ERROR, "01", "File not found"])
    else:
        return create_msg([ERROR, "00", "Not Defined"])


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
def check_acknowledgement(client_socket, packet, address):
    received_appropriate_packet = False
    msg_waiting_for_ack_params = socket_dict[client_socket][2]
    try:
        if packet[1][1] != address[1]:
            error_handler(client_socket, packet[1], None, UNKNOWN_ID)
            # send_msg(params_error_list, packet[1], client_socket, 0, False)
        else:
            packet_params = parser(packet[0])
            if msg_waiting_for_ack_params[0] == DATA:
                if packet_params[0] == ACK and packet_params[1] == msg_waiting_for_ack_params[1]:
                    received_appropriate_packet = True
                elif packet_params[0] == ERROR:
                    received_appropriate_packet = True
                elif len(msg_waiting_for_ack_params[2]) <= MAX_DATA_LEN:
                    received_appropriate_packet = True
            elif msg_waiting_for_ack_params[0] == ACK:
                if packet_params[0] == DATA or packet_params[0] == ERROR:
                    received_appropriate_packet = True
        socket_dict[client_socket][0] = 1
        socket_dict[client_socket][1] = packet_params
        return packet_params
    except OSError as os_err:
        print(os_err)
        client_socket.close()
        socket_dict[client_socket][0] = -1
        exit(1)


def timer_thread_for_recv(sock):
    socket_dict[sock][9] = False
    readable, writable, = select(socket_to_recv_list, [], [])
    if sock in readable:
        packet = sock.recvfrom(MAX_DATA_LEN * 2)
        socket_dict[sock][7] = packet
        socket_dict[sock][9] = True


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
            writable, readable, = select([server_socket], _, _)
            # check if out server is readable
            # which means he is ready to accept new client
            if server_socket in readable:
                # when we get first_packet - client tries to reach server
                first_packet = server_socket.recvfrom((MAX_DATA_LEN * 2))
                # allocate random port for client and open socket
                random_port = random.randint(0, 65535)  # this is the range of valid ports
                client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                client_socket.bind(('', random_port))
                # take msg from packet
                msg = first_packet[0]
                msg_params = parser(msg)
                # analyzing which packet it is and send it to relevant command
                # while paying attention to select
                msg = first_packet[0]
                msg_params = parser(msg)
                # dict value is (file_path, req_id, msg_to_send, offset, address,
                #               block_number, is_finished, data_recieved, retransmit_counter, timer_thread,
                #               recv_from_succeeded...)
                #  first creation of socket key in dict
                socket_dict[socket] = (msg_params[1], msg_params[0], None, 0, first_packet[1], 0,
                                       False, None, max_retransmission)

            # update dict of sockets that wait for sendto
            update_before_send_dict()
            # Check who is writable and send him packet
            readable, writable, = select([], socket_to_send_list, [])
            for writable_socket in writable:
                writable_socket.sendto(socket_dict[writable_socket][2], socket_dict[writable_socket][4])
                # TODO here we will do re-transimt and timer thread
                socket_to_recv_list.append(writable_socket)
                socket_to_send_list.remove(writable_socket)
                if socket_dict[writable_socket][8] > 0:
                    socket_dict[writable_socket][9] = Timer(timeout_in_seconds, timer_thread_for_recv, writable_socket)
                    socket_dict[writable_socket][9].start()
                    # if timer thread finished and we didn't receive packet
                    if not socket_dict[writable_socket][9].isalive() and not socket_dict[writable_socket][9]:
                        socket_dict[writable_socket][8] -= 1
                        socket_to_send_list.append(writable_socket)
                    elif socket_dict[writable_socket][9]:
                        check_acknowledgement(writable_socket,
                                              socket_dict[writable_socket][7], socket_dict[writable_socket][4])
                else:
                    print("Connection Timeouted for", writable_socket[0])
                    writable_socket.close()

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
