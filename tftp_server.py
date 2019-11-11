import socket
import sys
import errno
import argparse
import os
import struct


#global variables and constants :

TID = 0 #global TID variable
DATA_len = 512
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


#the inverse-parser : get msg type number  params_list of the message we want to send as declared in
#the protocol and its length. also get address (host,port) , socket_server, mode of connecrion (read or write)
#and a retransmit counter.
#the function create a byte-decoded message for reacj message type as declared in the protocol
#and call to send_message in order to send the byte-coded massage.


def create_msg_and_send_it(opcode, *args):
    msg = [opcode, args[0]]
    if opcode == 1 or opcode == 2:
        msg.append(0)
        msg.append("octet")
        msg.append(0)
    elif opcode == 3 or opcode == 5:
        msg.append(args[1])
    msg.extend([0] * (512 - len(msg)))
    return msg


def create_msg_and_send_it( msg_type, params_list, params_list_len, addr, soc_server, retransmit_counter):
    msg_type = params_list[0]
    msg = ""
    for i in range(params_list_len) : # !!!!!!need to fix!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! not a correct byte number
        msg = msg + params_list[i]
    return send_msg(msg_type, msg.decode(), params_list, addr, soc_server)

#gets message type, message(in byte-code) and address( = (host,address)) and send it to the client in addr
# it also return the the ack message received from it.
# if the connection timeouted, NONE is returned.
# if the message that was send is an error, no_request_need list is returned, and it's indicating that
# we can move on and sending the next message whithout the need to wait for an ack on it.
# if we sent DATA, ACK,WRQ,RRQ, the ack's params list on the sended message will be returned
def send_msg( current_msg_type, msg, msg_params_list , addr,sock_server , mode):
    sock_server.sendto(msd.encode(),addr)
    params_list = []
    no_request_need =[NO_REQUEST_NEEDED]

    if current_msg_type != ERROR :
        # wait for an appripriate acknoledge or timeout
        return wait_for_acknolegment(sock_server, params_list, mode)
    else :
        return no_request_need

# preforme the timeout and retransmit mechanism
# this function wait for acknolegment on dent message
# if the timeout expired, we will retransmit
# after 3 retransmits, we fill finish the connection
# if we got packet, we check if it is the ack we expected to. if so, we will return it's params list.
# otherwise, we will ignore the packet and wait for another one.
# if connection is timeout, None will be returned.
# else return the new message params list
def wait_for_acknolegment(sock_server ,msg_waiting_for_ack_params, retransmit_counter):
    received_appropriate_packet = 0
    params_error_list = [ERROR,"05","sent to wrong address, packet discarded", "0"]
    socket.settimeout(30.0)
    try :
        while received_appropriate_packet == 0:
            packet = sock_server.recvfrom((DATA_len*2))
            if packet[1][1] != TID:
                create_msg_and_send_it(ERROR, params_error_list, 4, packet[1])
                continue
            else:
                 packet_params = parser(packet)
                 if msg_waiting_for_ack_params[0] == DATA :
                    if packet_params[0] == ACK and packet_params[1] == msg_waiting_for_ack_params[1] :
                        received_appropriate_packet = 1
                    elif packet_params[0] == ERROR :
                        received_appropriate_packet = 1
                    else:
                        continue
                 elif  msg_waiting_for_ack_params[0] == ACK and MODE == READ_MODE :
                    if packet_params[0] == DATA or packet_params[0] == ERROR:
                        received_appropriate_packet = 1
                    else:
                        continue
                 elif msg_waiting_for_ack_params[0] == RRQ:
                    if packet_params[0] == DATA or packet_params[0] == ERROR:
                         received_appropriate_packet = 1
                    else:
                         continue
                 elif msg_waiting_for_ack_params[0] == WRQ:
                    if packet_params[0] == ACK and packet_params[1] == msg_waiting_for_ack_params[1]:
                        received_appropriate_packet = 1
                    elif packet_params[0] == ERROR:
                        received_appropriate_packet = 1
                    else:
                        continue
                 else : #which mean we got wrong packet type from the right port, therefore we will ignore it ????
                     continue
        return packet_params
    except OSError as os_err :
        if os_err == TimeoutError:
            if retransmit_counter < 4:
                retransmit_counter += 1
                create_msg_and_send_it(msg_waiting_for_ack_params[0], msg_waiting_for_ack_params, len(params_list),
                                         addr, sock_server, mode, retransmit_counter)
            else :
                return None
        else:
            print(os_err.stderror)
            sock_server.close()
            exit(1) #print error and break, is it the right handele ???????????????????????



def read(soc_serv,msg_params_list, addr):
    block_number = 0
    new_data_params = [DATA, "0", ""]
    try:
        f = open(msg_params_list[1], 'r')
    except OSError as err :
        print(err.stderror)
        if err == FileNotFoundError :
            create_msg_and_send_it(ERROR, [ERROR, "01", "File not found", "0"], 4, addr, soc_serv, 0)
        elif err == PermissionError :
            create_msg_and_send_it(ERROR, [ERROR, "02", "Access to file denied", "0"], 4, addr, soc_serv, 0)
        else:
            create_msg_and_send_it(ERROR, [ERROR, "00", "Unknown error while opening the file", "0"], 4, addr, soc_serv, 0)
        return
    got_to_eof = 0
    while got_to_eof == 0 :
        block_number += 1
        data = f.read(512)
        if len(data) < 512 :
            got_to_eof = 1
        new_data_params[1] = str(block_number)
        new_data_params[2] = data
        new_msg_params = create_msg_and_send_it(DATA, new_data_params, 3, addr, soc_serv, 0)
        if new_msg_params == None :
            print("Connection Timeouted")
            f.close()
            return
        elif new_msg_params[0] == ERROR :
            print( "Error Code : " + new_msg_params[1] + "Error Message : " + new_msg_params[2])
            f.close()
            return
        else: # which mean we got an ack on the data block we sent, and can continue
            continue
    f.close()
    return


#need to implement
def write(soc_serv, addr, path, adder):
    ack_params = [ACK, "0"]
    try:
        f = open(msg_params_list[1], 'a') # should it be a? or w ?
    except OSError as err:
        print(err.stderror)
        if err == FileExistsError:
            create_msg_and_send_it(ERROR, [ERROR, "06", "File already exists", "0"], 4, addr, soc_serv, 0)
        elif err == PermissionError:
            create_msg_and_send_it(ERROR, [ERROR, "02", "Access to file denied", "0"], 4, addr, soc_serv, 0)
        else: # what is the error for full memore ???
            create_msg_and_send_it(ERROR, [ERROR, "00", "unknown error while opening the file", "0"], 4, addr, soc_serv, 0)
        return
    got_to_eof = 0
    new_msg_params = create_msg_and_send_it(ACK, ack_params, 2, sddr, soc_serv, 0)
    while got_to_eof == 0:
        if new_msg_params == None :
            print("Connection Timeouted")
            f.close()
            return
        elif new_msg_params[0] == ERROR :
            print( "Error Code : " + new_msg_params[1] + "Error Message : " + new_msg_params[2])
            f.close()
            return
        else: #meams we got data block, according to send_msg
            data = new_msg_params[3]
            ack_params[1] = block_num = new_msg_params[2]
            f.write(data)
            new_msg_params = create_msg_and_send_it(ACK, ack_params, 2, sddr, soc_serv, 0)
            if len(data) < DATA_len:
                got_to_eof = 0
    f.close()
    return


def error_handler(soc_serv, addr, path, adder):

def parser(msg):
    opcode = msg[:2]
    msg = msg[2:]
    if opcode == 1 or opcode == 2:
        return opcode, msg[:bytes.find(b"0")], "octet"
    elif opcode == 3:
        return opcode, msg[:2], msg[2:]
    elif opcode == 4:
        return opcode, msg[2:]
    else:
        return opcode, msg[:2], msg[2:-1]


def main():
    error = 0
    controlC = 0
    if len(sys.argv) < 2:
        print("The program should get port number")
    else:
        port = int(sys.argv[1])
        try:
            soc_serv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            soc_serv.bind(('', port))
            soc_serv.listen(10)
            while error==0 and controlC ==0 : #need to add control+c handler !!!!!!!!!!!!!!!
                first_packet = soc_serv.recvfrom((DATA_len*2))
                msg = first_packet[0].encode()
                TID = first_packet[1][1]
                msg_params = parser(msg)
                if msg_params[0] == WRQ :
                    MODE = WRITE_MODE
                    write(msg_params)
                elif msg_params[0] == RRQ :
                    MODE = READ_MODE
                    read(msg_params)
                elif msg_params[0] == ERROR :
                    error_handler(msg_params)
                elif msg_params[0] == ACK or msg_params[0] == DATA :
                    continue #we shoukd ignore those message
            soc_serv.close()
        except OSError as error:
            soc_serv.close()
            print(error.stderror)

if __name__ == "__main__":
    main()