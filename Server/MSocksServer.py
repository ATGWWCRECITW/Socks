import logging, multiprocessing 
from TCPRely import *
multiprocessing.allow_connection_pickling()
logging.basicConfig(level=logging.DEBUG)
Config = json.load(open("Config.json"))

def GenerateUDPPortList(Ports):
    l = list()
    for Port in Ports:
        if isinstance(Port, int):
            l.append(Port)
        else:
            S,E = Port.split('-')
            l.extend(list(range(int(S),int(E)+1)))
    return l


def SubProcess(Switch, CPipe):
    Process = ServerTcpRelyProcess(Switch, CPipe)
    Process.Run()

if __name__ == '__main__':
    #UDPPorts = GenerateUDPPortList(Config["ServerUDPPorts"])
    #用于线程间通信
    ProcessList = list()
    #应支持多线程
    for i in range(0,1):
        SubProcessManager = dict()
        SubProcessManager["Handle"], Switch = socket.socketpair()
        SubProcessManager["PPipe"], CPipe = multiprocessing.Pipe()
        SubProcessManager["Process"] = multiprocessing.Process(target=SubProcess, args=(Switch, CPipe))
        SubProcessManager["Process"].start()
        ProcessList.append(SubProcessManager)

    Scoks5Server = TcpConnAccepter("0.0.0.0",Config["ServerPort"],ProcessList)
    try:
        Scoks5Server.Run()
    except KeyboardInterrupt as e:
        Scoks5Server.Stop()