import asyncio, socket, sys, os, logging, multiprocessing, json
from TCPClientProtocol import *
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Mod import pack, auth
class ClientTcpRelyProcess(object):
    """在子线程中运行管理ACSocket和SCSocket,
    建立连接并向客户端返回服务器连接信息，之后开始转发数据"""
    def __init__(self, Switch, Pipe):
        """Switch 是一个socket，每次传输1字节操作码,
        Pipe 为multiprocessing.Pipe()"""
        self.Switch = Switch
        self.Pipe = Pipe
        if sys.platform == 'win32':
            #由于后面的函数，必须使用get_event_loop
            logging.info("Platform Detected win32,TcpRely Use get_event_loop")
            self.Loop = asyncio.get_event_loop()
        else:
            logging.info("Platform Detected Unknow, Use get_event_loop")
            self.Loop = asyncio.get_event_loop()
    
    def SwitchManager(self):
        HandleCode = self.Switch.recv(1)
        if HandleCode == b'\x01':#接受新连接
            self.Loop.create_task(self.AddSocket())

    async def AddSocket(self):
        """初始化Protocol"""
        ConnectInfo = self.Pipe.recv()
        ACSocket = socket.fromfd(reduction.recv_handle(self.Pipe), ConnectInfo["AddressFamily"], ConnectInfo["SocketType"], ConnectInfo["SocketProto"])
        ACSocket.setblocking(False)
        #选择认证和数据传输方案
        Auther = auth.Authers[ConnectInfo["UserConfig"]["AuthMethod"]](ConnectInfo, self.Loop)
        Packer = pack.Packers[ConnectInfo["UserConfig"]["PackMethod"]](ConnectInfo, self.Loop)
        #注意这里用大小写P来区分类和变量
        try:
            #先准备FirstRequest，完成后再准备Auth数据
            ConnectInfo["FirstRequest"] = await Packer.FirstRequest(ConnectInfo, ACSocket)
        except ValueError as e:
            logging.debug("AddSocket Failed:%s"%str(e))
            ACSocket.close()
            return None
        if ConnectInfo["FirstRequest"] is not None:
            if ConnectInfo["CMD"] == 1:#CONN
                #logging.debug("connect Request")
                #把ACSocket添加至loop
                ACtransport,ACprotocol = await self.Loop.connect_accepted_socket(lambda:ACProtocol(ConnectInfo, Packer), ACSocket)
                ACtransport.pause_reading()
                #建立到服务器的连接
                SCSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                SCSocket.setblocking(False)
                await self.Loop.sock_connect(SCSocket, (ConnectInfo["UserConfig"]["ServerAddress"],ConnectInfo["UserConfig"]["ServerPort"]))
                #进行认证
                if Auther.RequestAuth(SCSocket) is True:
                    #发送第一次请求
                    SCSocket.send(ConnectInfo["FirstRequest"])
                    ConnectInfo["FirstResponse"] = await Packer.GetFirstResponse(SCSocket)
                    ACtransport.write(ConnectInfo["FirstResponse"])

                    SCtransport,SCprotocol = await self.Loop.connect_accepted_socket(lambda:SCProtocol(ConnectInfo, ACtransport, ACprotocol, Packer), SCSocket)
                    #恢复读取
                    ACtransport.resume_reading()
                else:
                    SCSocket.close()
            elif ConnectInfo["CMD"] == 2:#Bind
                logging.debug("Bind Request")
            elif ConnectInfo["CMD"] == 3:#UDP
                logging.debug("UDP Request")
                #把ACSocket添加至loop,注意此处为ACUProtocol而不是ACProtocol
                ACUtransport,ACUprotocol = await self.Loop.connect_accepted_socket(lambda:ACUProtocol(), ACSocket)
                #建立到服务器的连接
                SCSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                SCSocket.setblocking(False)
                await self.Loop.sock_connect(SCSocket, (ConnectInfo["UserConfig"]["ServerAddress"],ConnectInfo["UserConfig"]["ServerPort"]))
                #进行认证
                if Auther.RequestAuth(SCSocket) is True:
                    #发送第一次请求
                    SCSocket.send(ConnectInfo["FirstRequest"])
                    #接收第一次回复
                    ConnectInfo["FirstUDPResponse"] = await Packer.GetFirstUDPResponse(SCSocket, ClientBindAddr=SCSocket.getsockname())
                    print("FirstUDPResponse",ConnectInfo["FirstUDPResponse"], len(ConnectInfo["FirstUDPResponse"]))
                    #ClientBindAddr=SCSocket.getsockname()可能会导致无法接收非本地主机的请求
                    SCtransport,SCprotocol = await self.Loop.connect_accepted_socket(lambda:SCProtocol(ConnectInfo, ACUtransport, ACUprotocol, Packer), SCSocket)
                    ACUprotocol.SCtransport = SCtransport
                    #建立UDP, local_addr指定本地端口, remote_addr则会指定只接受的数据来源
                    UCtransport,UCprotocol = await self.Loop.create_datagram_endpoint(lambda:UCProtocol(ConnectInfo, Packer, ACUtransport, AppAddr=(SCSocket.getsockname()[0], ConnectInfo["Port"]),ServerAddr=(ConnectInfo["UDPHost"], ConnectInfo["UDPPort"])), local_addr=SCSocket.getsockname())
                    ACUprotocol.UCtransport = UCtransport
                    #发送第一次回复至app
                    ACSocket.send(ConnectInfo["FirstUDPResponse"])
                else:
                    SCSocket.close()
        else:
            ACSocket.close()


    def Run(self):
        """开启服务"""
        self.Loop.add_reader(self.Switch,self.SwitchManager)
        try:
            self.Loop.run_forever()
        except KeyboardInterrupt as e:
            self.Stop()

    def Stop(self):
        """结束服务"""
        self.Loop.close()


class Socks5TcpAccepter(object):
    """接受客户端连接，并完成初始认证，
    随后把socket交给后端处理"""
    def __init__(self, Host, Port, OutPutList):
        """"OutPut是用来接受输出列表的函数"""
        self.Host = Host
        self.Port = Port
        self.count = 0
        self.OutPutList = OutPutList
        #根据平台选择loop类型
        if sys.platform == 'win32':
            logging.info("Platform Detected win32,Socks5TcpAccepter Use get_event_loop")
            self.Loop = asyncio.get_event_loop()
            #self.Loop = asyncio.ProactorEventLoop()
        else:
            logging.info("Platform Detected Unknow, Use get_event_loop")
            self.Loop = asyncio.get_event_loop()
        #设置服务器
        self.Server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.Server.setblocking(False)
        self.Server.bind((self.Host,self.Port))
        self.Server.listen(64)

    async def CompleteSocks5Auth(self, ACSocket, ConnectInfo):
        ############
        #  第一次连接
        ############
        #VER,NMETHODS = b'\x05\x01' ===> VER=5,NMETHODS=1
        #VER = b'\x05' ===> VER = b'\x05'
        try:
            VER = await self.Loop.sock_recv(ACSocket, 1)
            NMETHODS = await self.Loop.sock_recv(ACSocket, 1)
            if VER != b'\x05': #b'\x05'
                ACSocket.close()
                return None
            METHODS = await self.Loop.sock_recv(ACSocket, struct.unpack('>B', NMETHODS)[0])
            #print("VER,METHODS",VER,METHODS)
            #检查模式
            if b'\x00' not in METHODS:
                ACSocket.close()
                return None
            #返回模式
            self.Loop.sock_sendall(ACSocket, b'\x05\x00')
            #logging.info("Complete The PerAuth")
        except (ValueError,TimeoutError,socket.timeout) as e:
            logging.debug("CompleteSocks5Auth Filed:%s"%e)
            logging.debug("Addr:%s:%s"%ACSocket.getpeername())
            ACSocket.close()
            return None
        ############
        #  第二次连接,由转发线程完成
        ############
        self.OutPut(ACSocket,ConnectInfo)

    def GetUserConfig(self):
        """从设置列表中选择一个服务器进行连接,可以在此处增加负载均衡等逻辑"""
        UserConfigs = json.load(open("ClientConfig.json"))
        for UserConfig in UserConfigs:
            if UserConfig["Default"] is True:
                return UserConfig

    def Accepter(self):
        """完成socks5认证工作,考虑到工作强度的关系,GetUserConfig在此处完成"""
        ACSocket,addr = self.Server.accept()
        ConnectInfo = {"AddressFamily":ACSocket.family,
                        "SocketType":ACSocket.type,
                        "SocketProto":ACSocket.proto,
                        "UserConfig":self.GetUserConfig()}
        self.Loop.create_task(self.CompleteSocks5Auth(ACSocket, ConnectInfo))

    def Run(self):
        """开启服务"""
        self.Loop.add_reader(self.Server,self.Accepter)
        logging.info("Server Started")
        self.Loop.run_forever()

    def Stop(self):
        """结束服务"""
        self.Loop.close()

    def OutPut(self, CtSSocket, ConnectInfo):
        """输出Socket"""
        #装作负载均衡
        self.count = (self.count+1)%len(self.OutPutList)
        ProcessManager = self.OutPutList[self.count]
        ProcessManager["PPipe"].send(ConnectInfo)
        #linux下传递handel不需要pid
        reduction.send_handle(ProcessManager["PPipe"], CtSSocket.fileno(), ProcessManager["Process"].pid)
        ProcessManager["Handle"].send(b'\x01')