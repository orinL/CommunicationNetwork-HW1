#!/usr/bin/python3
import socket
import sys
import struct
import errno
import random
from threading import Timer
import selectors

sel = selectors.DefaultSelector()

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

# global lists:
timer_threads_lst = []
socket_lst = []


# SocketDetails class is a class that obtains every detail a client socket need when
# it tries to communicate with the server
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


# Input: nothing
# Output: nothing
# Goal: update the msg_to_send in the relevant field in the relevant class
def update_before_send(details):
    try:
        # if we received packet and it was from wrong TID
        if details.packet_recv is not None:
            if details.packet_recv[1][1] != details.address[1]:
                details.msg_to_send = error_handler(None, UNKNOWN_ID)
                return details
        # if his request was RRQ
        if details.req_id == RRQ:
            # open file path
            f = open(details.file_path, 'r')
            # move to offset according to what we already read
            f.seek(details.offset)
            # read relevant data
            data = f.read(MAX_DATA_LEN)
            # since we are read - first block number is 1
            if details.block_number == 0:
                details.block_number = 1
            # prepare new packet to send
            new_data_params = [DATA, details.block_number, data]
            details.msg_to_send = create_msg(new_data_params)
            # close file descriptor
            f.close()
            return details
        # if his request was WRQ
        elif details.req_id == WRQ:
            # build ack message
            ack_params = [ACK, details.block_number]
            # try to open and write the data
            f = open(details.file_path, 'a')
            # if we are not sending first ack param
            if details.block_number > 0:
                # we need to extract data to write from packet we got
                new_msg_params = parser(details.packet_recv[0])
                data_msg = new_msg_params[2]
                f.write(data_msg)
                f.close()
            # update msg_to_send
            details.msg_to_send = create_msg(ack_params)
        # if we got error packet - we send error msg to client
        else:
            details.msg_to_send = error_handler(None, ILLEGAL)
        return details
    except OSError as err:
        print(err)
        # if an error occured, the msg_to_send is going to be error msg
        details.msg_to_send = error_handler(err, WRQ)
        return details


# Input: socket, address, error, mode
# Output: creates the relevant message to the client. Returns packed msg
# Notes: messages according to protocol
def error_handler(err, mode):
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


# Input: client_socket, packet we received, address
# Output: True if we got correct packet, False o/w
# Notes: we check if it is the ack we expected to(ACK or DATA).
def check_acknowledgement(client_socket, packet, address, msg_to_send):
    received_appropriate_packet = False
    msg_waiting_for_ack_params = parser(msg_to_send)
    try:
        if packet[1][1] != address[1]:
            # we will send Error message when we get to update_before_send_dict
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
        return received_appropriate_packet
    except OSError as os_err:
        print(os_err)
        for client_socket in socket_lst:
            client_socket.close()
        for timer_thread in timer_threads_lst:
            timer_thread.cancel()
        exit(1)


# Input: client_socket
# Output: nothing
# Notes: if timer finishes and we didn't cancel it we will get here and handle re-transmit
def timer_handler(client_socket, data):
    # decrease retransmit counter
    data.counter -= 1
    # add to send to socket list in order to re-transmit
    sel.unregister(client_socket)
    data = update_before_send(data)
    sel.register(client_socket, selectors.EVENT_WRITE, data)


# Input: client_socket
# Output: True if we got correct packet, False o/w
# Notes: we received a packet so we check if it's the correct one and we act correspondly
def handle_recv_packet(client_socket, data):
    # check if we got correct packet
    if check_acknowledgement(client_socket,
                             data.packet_recv, data.address, data.msg_to_send):
        # remove socket from socket_to_recv_list
        sel.unregister(client_socket)
        # socket_to_recv_list.remove(client_socket)
        new_msg_params = parser(data.packet_recv[0])
        if new_msg_params[0] == ERROR:
            return
        # if we are not finished
        if not data.is_finished:
            # update offset
            data.offset += MAX_DATA_LEN
            # update block number according to req_id
            if data.req_id == RRQ:
                data.block_number += 1
            elif data.req_id == WRQ:
                data.block_number = new_msg_params[1]
            # add socket to send to list
            # socket_to_send_list.append(client_socket)
            data = update_before_send(data)
            sel.register(client_socket, selectors.EVENT_WRITE, data)
    # if we didn't get correct message we leave socket in socket_to_recv_list in order to try again to receive it


# Input: writable_socket
# Output: True if we have more chance to send message, False o/w
# Notes: check if we can still try to send message and open timer if we can,
#        otherwise, announce we Timouted
def create_timer_thread_and_handle_retransmit(writable_socket, data):
    # if we can re-transmit
    if data.counter > 0:
        # remove socket from socket_to_recv_list
        # since we will add it again after we sendto again
        # if we are not done
        if not data.is_finished:
            # create timer thread
            data.timer_thread = \
                Timer(timeout_in_seconds, timer_handler, (writable_socket, data))
            # append timer thread to list
            timer_threads_lst.append(data.timer_thread)

            # execute timer
            data.timer_thread.start()
        return data.timer_thread
    # if we can't retransmit anymore
    else:
        # print relevant message and update lists and dict
        print("Connection Timeouted for ", data.address)
        # close socket
        writable_socket.close()
        return None


# Input: client_socket
# Output: nothing
# Notes: update the is_finished field in class
def update_is_finished(client_socket, data):
    # if we received a packet
    if not data.packet_recv is None:
        new_msg_params = parser(data.packet_recv[0])
        # check if we got error packet
        if new_msg_params[0] == ERROR:
            print("Error Code : " + new_msg_params[1] + " ,Error Message : " + new_msg_params[2])
            data.is_finished = True
        # if we are in WRQ and data len is smaller than MAX_DATA_LEN
        elif data.req_id == WRQ:
            data_msg = new_msg_params[2]
            if len(data_msg) < MAX_DATA_LEN:
                data.is_finished = True
    # if we sent a packet
    new_msg_params = parser(data.msg_to_send)
    # if we are in RRQ and data len is smaller than MAX_DATA_LEN
    if data.req_id == RRQ:
        data_msg = new_msg_params[2]
        if len(data_msg) < MAX_DATA_LEN:
            data.is_finished = True
    elif new_msg_params[0] == ERROR:
        data.is_finished = True
    return data.is_finished


# Main
def main(port):
    socket_created = False
    try:
        if not (1 <= port <= 65535):
            raise ValueError
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        socket_created = True
        server_socket.bind(('', port))
        # register server socket with READ event
        server_socket.setblocking(False)
        sel.register(server_socket, selectors.EVENT_READ, data=None)
        while True:
            events = sel.select(0)
            for key, mask in events:
                # if this is listening socket
                if key.data is None:
                    first_packet = server_socket.recvfrom((MAX_DATA_LEN * 2))
                    # allocate random port for client and open socket
                    random_port = random.randint(0, 65535)  # this is the range of valid ports
                    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    client_socket.bind(('', random_port))
                    # add socket to list
                    socket_lst.append(client_socket)
                    client_socket.setblocking(False)
                    # take msg from packet
                    msg = first_packet[0]
                    # parsing byte message to parameters - [REQ_ID, PATH, 0 , MODE, 0]
                    msg_params = parser(msg)
                    # create SocketDetails for each client socket we create
                    # SocketDetails - req_id, file_path, msg_to_send, offset, address, block_number, is_finished,
                    #                 packet_recv, counter, timer_thread
                    # first we need to send the client socket a message
                    data = SocketDetails(msg_params[0], msg_params[1], None, 0, first_packet[1],
                                         0, False, None, max_retransmission + 1, None)
                    # register client_socket to client selector
                    data = update_before_send(data)
                    sel.register(client_socket, selectors.EVENT_WRITE, data=data)
                # else this is client socket
                else:
                    # Check who is writable and send him relevant packet
                    sock = key.fileobj
                    data = key.data
                    # if it is readable socket
                    if mask & selectors.EVENT_READ:
                        packet = sock.recvfrom(MAX_DATA_LEN * 2)
                        data.timer_thread.cancel()
                        # remove timer thread from list
                        timer_threads_lst.remove(data.timer_thread)
                        data.timer_thread = None
                        data.packet_recv = packet
                        handle_recv_packet(sock, data)
                    # if it is writable socket
                    if mask & selectors.EVENT_WRITE:
                        sock.sendto(data.msg_to_send, data.address)
                        if data.timer_thread is None:
                            # since we need to re-send max_retransmission times
                            data.counter = max_retransmission + 1
                        data.is_finished = update_is_finished(sock, data)
                        # re-transmit and timer thread
                        data.timer_thread = create_timer_thread_and_handle_retransmit(sock, data)
                        # if we didn't use all of the re-transmit tries
                        if data.timer_thread is not None:
                            # unregister from WRITE
                            sel.unregister(sock)
                            if not data.is_finished:
                                # register to READ so we can send to
                                sel.register(sock, selectors.EVENT_READ, data)
                            # if we are finished we can close
                            else:
                                socket_lst.remove(sock)
                                sock.close()
                        # otherwise we timeouted the connection so we need to unregister it
                        else:
                            sel.unregister(sock)
        server_socket.close()
    except OSError as error:
        if socket_created:
            server_socket.close()
        print(error)
        for client_socket in socket_lst:
            client_socket.close()
        for timer_thread in timer_threads_lst:
            timer_thread.cancel()
        exit(1)
    except KeyboardInterrupt:
        if socket_created:
            server_socket.close()
        print("\nBye Bye")
        for client_socket in socket_lst:
            client_socket.close()
        for timer_thread in timer_threads_lst:
            timer_thread.cancel()
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
