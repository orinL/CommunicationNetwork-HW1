import socket
import sys
import errno
import argparse
import os
import struct

# global variables and constants :

TID = 0  # global TID variable
MAX_DATA_LEN = 512
RRQ = "01"
WRQ = "02"
DATA = "03"
ACK = "04"
ERROR = "05"

NO_REQUEST_NEEDED = "06"
BREAK_ERROR = "07"

READ_MODE = 0
WRITE_MODE = 1

MODE = -1


def create_msg(msg_params):
    # TODO change to struct pack
    opcode = msg_params[0]
    msg_params = msg_params[1:]
    msg = b'0'
    if opcode == RRQ or opcode == WRQ:
        msg = struct.pack(f"h{len(msg_params[0])}ss5ss",
                          int(opcode), msg_params[0].encode(), "0".encode(), "octet".encode(), "0".encode())
        # msg = opcode + msg_params[0] + "0" + "octet" + "0"
        # msg = msg.encode()
        print("msg in RRQ/WRQ is ", struct.unpack(f"h{len(msg_params[0])}ss5ss", msg))
    elif opcode == DATA:
        msg = struct.pack(f">hh{len(msg_params[1])}s", int(opcode), msg_params[0], msg_params[1].encode())

        # block_number = struct.pack(">h", msg_params[0])
        # print("msg in Data before is ", msg.decode())
        # msg += msg_params[1].encode()
        print("msg in Data in bytes ", msg)
        print("msg in Data is ", struct.unpack(f">hh{len(msg_params[1])}s", msg))
    elif opcode == ACK:
        msg = struct.pack(">hh", int(opcode), msg_params[0])
        print("msg in Ack is ", struct.unpack(">hh", msg))
    elif opcode == ERROR:
        msg = opcode + msg_params[0] + msg_params[1] + "0"
        msg = msg.encode()
        print("msg in Error is ", msg.decode())
    return msg


# the inverse-parser : get msg type number  params_list of the message we want to send as declared in
# the protocol and its length. also get address (host,port) , socket_server, mode of connecrion (read or write)
# and a retransmit counter.
# the function create a byte-decoded message for reacj message type as declared in the protocol
# and call to send_message in order to send the byte-coded massage.


# gets message type, message(in byte-code) and address( = (host,address)) and send it to the client in address
# it also return the the ack message received from it.
# if the connection timeouted, NONE is returned.
# if the message that was send is an error, no_request_need list is returned, and it's indicating that
# we can move on and sending the next message whithout the need to wait for an ack on it.
# if we sent DATA, ACK,WRQ,RRQ, the ack's params list on the sended message will be returned
def send_msg(msg_params, address, sock_server, retransmit_counter):
    msg = create_msg(msg_params)
    sock_server.sendto(msg, address)
    print("Server sent ", msg_params, msg)
    no_request_need = [NO_REQUEST_NEEDED]
    if msg_params[0] != ERROR:
        # wait for an appropriate acknowledgement or timeout
        return wait_for_acknowledgement(sock_server, msg_params, retransmit_counter, address)
    # TODO if we implement error_handler then update this funct
    else:
        return no_request_need


# perform the timeout and retransmit mechanism
# this function wait for acknowledgement on sent message
# if the timeout expired, we will retransmit
# after 3 retransmits, we fill finish the connection
# if we got packet, we check if it is the ack we expected to. if so, we will return it's params list.
# otherwise, we will ignore the packet and wait for another one.
# if connection is timeout, None will be returned.
# else return the new message params list
def wait_for_acknowledgement(sock_server, msg_waiting_for_ack_params, retransmit_counter, address):
    received_appropriate_packet = False
    params_error_list = [ERROR, "05", "sent to wrong address, packet discarded", "0"]
    sock_server.settimeout(30.0)
    try:
        packet_params = []
        while not received_appropriate_packet:
            packet = sock_server.recvfrom(MAX_DATA_LEN * 2)
            if packet[1][1] != address[1]:
                send_msg(params_error_list, packet[1], sock_server, 0)
                continue
            else:
                packet_params = parser(packet[0])
                print("packet_params", packet_params)
                print("msg waiting for ack", msg_waiting_for_ack_params)
                if msg_waiting_for_ack_params[0] == DATA:
                    if packet_params[0] == ACK and packet_params[1] == msg_waiting_for_ack_params[1]:
                        received_appropriate_packet = True
                    elif packet_params[0] == ERROR:
                        received_appropriate_packet = True
                    else:
                        continue
                elif msg_waiting_for_ack_params[0] == ACK:
                    if packet_params[0] == DATA or packet_params[0] == ERROR:
                        received_appropriate_packet = True
                    else:
                        continue
                else:  # which mean we got wrong packet type from the right port, therefore we will ignore it ????
                    continue
        return packet_params
    except OSError as os_err:
        if os_err == TimeoutError:
            if retransmit_counter < 4:
                send_msg(msg_waiting_for_ack_params, address, sock_server, retransmit_counter + 1)
            else:
                return None
        else:
            # print(os_err.stderror)
            sock_server.close()
            exit(1)  # print error and break, is it the right handele ???????????????????????


def read(soc_serv, msg_params_list, addr):
    block_number = 0
    new_data_params = [DATA, "0", ""]
    try:
        f = open(msg_params_list[1], 'r')
    except OSError as err:
        # print(err.stderror)
        error_handler(soc_serv, addr, err)
        return
    got_to_eof = 0
    while got_to_eof == 0:
        block_number += 1
        data = f.read(512)
        if len(data) < 512:
            got_to_eof = 1
        new_data_params[1] = block_number
        new_data_params[2] = data
        # checking for ack right params in send_msg
        new_msg_params = send_msg(new_data_params, addr, soc_serv, 0)
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
    return


def write(sock, address, msg_params):
    # 0 is block number
    ack_params = [ACK, 0]
    try:
        f = open(msg_params[1], 'a')  # should it be a? or w ?
    except OSError as err:
        # print(err.stderror)
        error_handler(sock, address, err)
        return
    got_to_eof = 0
    new_msg_params = send_msg(ack_params, address, sock, 0)
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
            new_msg_params = send_msg(ack_params, address, sock, 0)
            if len(data) < MAX_DATA_LEN:
                got_to_eof = 0
    f.close()
    return


def error_handler(sock, address, err):
    if err == FileExistsError:
        send_msg([ERROR, "06", "File already exists"], address, sock, 0)
    elif err == PermissionError:
        send_msg([ERROR, "02", "Access to file denied", "0"], address, sock, 0)
    if err == FileNotFoundError:
        send_msg([ERROR, "01", "File not found", "0"], address, sock, 0)
    else:  # what is the error for full memory ???
        send_msg([ERROR, "00", "unknown error while opening the file", "0"], address, sock, 0)
    return None


def parser(msg):
    print("msg[:2] is ", msg[:2])
    print("msg[2:] is ", msg[2:])
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


def main(port):
    socket_created = False
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        socket_created = True
        server_socket.bind(('', port))
        while True:
            first_packet = server_socket.recvfrom((MAX_DATA_LEN * 2))
            msg = first_packet[0]
            msg_params = parser(msg)
            if msg_params[0] == WRQ:
                print("Server got write request")
                write(server_socket, first_packet[1], msg_params)
            elif msg_params[0] == RRQ:
                print("Server got read request")
                read(server_socket, msg_params, first_packet[1])
            elif msg_params[0] == ERROR:
                print("Server got error message")
                error_handler(socket, first_packet[1], msg_params)
            elif msg_params[0] == ACK or msg_params[0] == DATA:
                continue  # we shoukd ignore those message
        server_socket.close()
    except OSError as error:
        if socket_created:
            server_socket.close()
        # print(error.stderror)
    except KeyboardInterrupt:
        if socket_created:
            server_socket.close()
        print("\nBye Bye")
        exit(0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("The program should get port number")
    else:
        port = int(sys.argv[1])
        main(port)
