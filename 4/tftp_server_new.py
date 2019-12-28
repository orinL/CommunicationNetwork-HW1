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


class SocketDetails:
    def __init__(self, req_id, file_path, msg_to_send, offset, address,
                 block_number, is_finished, packet_recv, counter, timer_thread):
        self.file_path = file_path
        self.req_id = req_id
        self.msg_to_send = msg_to_send
        self.offset = offset
        self.address = address
        self.block_number = block_number
        self.is_finished = is_finished
        self.packet_recv = packet_recv
        self.counter = counter
        self.timer_thread = timer_thread


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


def update_before_send_dict():
    for sock, details in socket_dict.items():
        if sock in socket_to_send_list:
            if details.req_id == RRQ:
                try:
                    f = open(details.file_path, 'r')
                except OSError as err:
                    print(err)
                    details.msg_to_send = error_handler(sock, details.address, err, RRQ)
                    return
                # move to offset according to what we already read
                f.seek(details.offset)
                data = f.read(MAX_DATA_LEN)

                if details.block_number == 0:
                    details.block_number = 1
                # prepare new packet to send
                new_data_params = [DATA, details.block_number, data]
                details.msg_to_send = create_msg(new_data_params)
                f.close()
            elif details.req_id == WRQ:
                ack_params = [ACK, details.block_number]
                try:
                    f = open(details.file_path, 'a')
                except OSError as err:
                    print(err)
                    details.msg_to_send = error_handler(sock, details.address, err, WRQ)
                    return

                # if we are not sending first ack param
                if details.block_number > 0:
                    new_msg_params = parser(details.packet_recv[0])
                    data = new_msg_params[2]
                    f.write(data)
                    f.close()
                details.msg_to_send = create_msg(ack_params)
            else:
                details.msg_to_send = error_handler(sock, details[4], None, ILLEGAL)


# Input: socket, address, error, mode
# Output: creates the relevant message to the client. Returns packed msg
# Notes: messages according to protocol
def error_handler(sock, address, err, mode):
    # if we have error while receiving packet we finish connection
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
    msg_waiting_for_ack_params = parser(socket_dict[client_socket].msg_to_send)
    try:
        if packet[1][1] != address[1]:
            error_handler(client_socket, packet[1], None, UNKNOWN_ID)
            return False
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
        # print("acked block# ", packet_params[1], "when I had ", msg_waiting_for_ack_params[1])
        # print("boolean ", received_appropriate_packet)
        return received_appropriate_packet
    except OSError as os_err:
        print(os_err)
        client_socket.close()
        exit(1)


# if timer finishes and we didn't cancel it
def timer_handler(client_socket):
    # if we didn't receive packet - this is why we got to handler
    # decrease retransmit counter
    socket_dict[client_socket].counter -= 1
    # add to send to socket list
    socket_to_send_list.append(client_socket)


# we received a packet - let's check it
def handle_recv_packet(client_socket):
    # check if we got correct packet
    if check_acknowledgement(client_socket,
                             socket_dict[client_socket].packet_recv, socket_dict[client_socket].address):
        socket_to_recv_list.remove(client_socket)
        new_msg_params = parser(socket_dict[client_socket].packet_recv[0])
        if new_msg_params[0] == ERROR:
            return

        if not socket_dict[client_socket].is_finished:
            socket_dict[client_socket].offset += MAX_DATA_LEN
            if socket_dict[client_socket].req_id == RRQ:
                socket_dict[client_socket].block_number += 1
            elif socket_dict[client_socket].req_id == WRQ:
                socket_dict[client_socket].block_number = new_msg_params[1]
            socket_to_send_list.append(client_socket)


def create_timer_thread_and_handle_retransmit(writable_socket):
    # if we can re-transmit
    if socket_dict[writable_socket].counter > 0:
        if not socket_dict[writable_socket].is_finished:
            # create timer thread
            socket_dict[writable_socket].timer_thread = \
                Timer(timeout_in_seconds, timer_handler, writable_socket)
            # execute timer
            socket_dict[writable_socket].timer_thread.start()
    # if we can't retransmit anymore
    else:
        print("Connection Timeouted for", writable_socket[0])
        if writable_socket in socket_to_send_list:
            socket_to_send_list.remove(writable_socket)
        if writable_socket in socket_to_recv_list:
            socket_to_recv_list.remove(writable_socket)
        del socket_dict[writable_socket]
        writable_socket.close()


def update_is_finished(client_socket):
    if not socket_dict[client_socket].packet_recv is None:
        new_msg_params = parser(socket_dict[client_socket].packet_recv[0])
        if new_msg_params[0] == ERROR:
            print("Error Code : " + new_msg_params[1] + " ,Error Message : " + new_msg_params[2])
            socket_dict[client_socket].is_finished = True
        elif socket_dict[client_socket].req_id == WRQ:
            data = new_msg_params[2]
            if len(data) < MAX_DATA_LEN:
                socket_dict[client_socket].is_finished = True
    new_msg_params = parser(socket_dict[client_socket].msg_to_send)
    data = new_msg_params[2]
    if socket_dict[client_socket].req_id == RRQ:
        if len(data) < MAX_DATA_LEN:
            socket_dict[client_socket].is_finished = True
    elif new_msg_params[0] == ERROR:
        socket_dict[client_socket].is_finished = True

# Main
def main(port):
    socket_created = False
    try:
        if not (1 <= port <= 65535):
            raise ValueError
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        socket_created = True
        server_socket.bind(('', port))
        while True:
            readable, writable, x = select([server_socket], [], [], 1)
            # check if our server is readable
            # which means it is ready to accept new client
            if server_socket in readable:
                # when we get first_packet - client tries to reach server
                first_packet = server_socket.recvfrom((MAX_DATA_LEN * 2))
                # allocate random port for client and open socket
                random_port = random.randint(0, 65535)  # this is the range of valid ports
                client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                client_socket.bind(('', random_port))
                # take msg from packet
                msg = first_packet[0]
                # parsing byte message to parameters - [REQ_ID, PATH, 0 , MODE, 0]
                msg_params = parser(msg)
                # create SocketDetails for each client socket we create
                # SocketDetails - req_id, file_path, msg_to_send, offset, address, block_number, is_finished,
                #                 packet_recv, counter, timer_thread
                socket_dict[client_socket] = SocketDetails(msg_params[0], msg_params[1], None, 0, first_packet[1],
                                                           0, False, None, max_retransmission, None)
                # first we need to send the client socket a message
                socket_to_send_list.append(client_socket)
            # update dict of sockets that wait for sendto
            update_before_send_dict()
            # Check who is writable and send him relevant packet
            readable, writable, x = select([], socket_to_send_list, [], 1)
            for writable_socket in writable:
                writable_socket.sendto(socket_dict[writable_socket].msg_to_send, socket_dict[writable_socket].address)
                # print("sent block# ", parser(socket_dict[writable_socket].msg_to_send)[1])
                socket_dict[writable_socket].counter = max_retransmission
                update_is_finished(writable_socket)
                if not socket_dict[writable_socket].is_finished:
                    socket_to_recv_list.append(writable_socket)
                socket_to_send_list.remove(writable_socket)
                # re-transmit and timer thread
                create_timer_thread_and_handle_retransmit(writable_socket)
            # for every socket we didn't receive response from
            readable, writable, x = select(socket_to_recv_list, [], [], 1)
            for sock in readable:
                packet = sock.recvfrom(MAX_DATA_LEN * 2)
                socket_dict[sock].timer_thread.cancel()
                socket_dict[sock].packet_recv = packet
                handle_recv_packet(sock)
            # for every socket we finished the connection with it
            finished_lst = [sock for sock in socket_dict.keys() if socket_dict[sock].is_finished]
            for finished_socket in finished_lst:
                del socket_dict[finished_socket]
                if finished_socket in socket_to_recv_list:
                    socket_to_recv_list.remove(finished_socket)
                if finished_socket in socket_to_send_list:
                    socket_to_send_list.remove(finished_socket)
                finished_socket.close()

        server_socket.close()
    except OSError as error:
        if socket_created:
            server_socket.close()
        for client_socket in list(socket_dict.keys()):
            client_socket.close()
        print(error)
    except KeyboardInterrupt:
        if socket_created:
            server_socket.close()
        for client_socket in list(socket_dict.keys()):
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
        max_retransmission = int(sys.argv[3])
        main(port)
