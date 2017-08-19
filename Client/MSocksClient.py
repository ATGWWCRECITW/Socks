import time, asyncio, socket, sys, struct, logging
import Config
from TCPClientProtocol import *
from TCPRely import *
import time
multiprocessing.allow_connection_pickling()
logging.basicConfig(level=logging.DEBUG)
Config = json.load(open("ClientConfig.json"))
def SubProcess(Switch, CPipe):
    Process = ClientTcpRelyProcess(Switch, CPipe)
    Process.Run()

if __name__ == '__main__':
    #用于线程间通信
    OutPutList = list()
    #应支持多线程
    for i in range(0,1):
        SubProcessManager = dict()
        SubProcessManager["Handle"], Switch = socket.socketpair()
        SubProcessManager["PPipe"], CPipe = multiprocessing.Pipe()
        SubProcessManager["Process"] = multiprocessing.Process(target=SubProcess, args=(Switch, CPipe))
        SubProcessManager["Process"].start()
        while (SubProcessManager["Process"].pid is None):
            time.sleep(0.1)
        OutPutList.append(SubProcessManager)

    Scoks5Client = Socks5TcpAccepter(Config["ClientBindAddress"],Config["ClientPort"],OutPutList)
    try:
        Scoks5Client.Run()
    except KeyboardInterrupt as e:
        Scoks5Client.Stop()