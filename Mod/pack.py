import asyncio, socket, logging, struct
class Pack(object):

    def __init__(self,ConnectInfo,Loop):
        """初始化时会传入连接信息"""
        self.ConnectInfo = ConnectInfo
        self.Loop = Loop

    async def FirstRequest(self, ConnectInfo, ACSocket):
        """生成第一次请求,TCP/UDP通用函数,
        在UDP情况下按照socks5的设计,此处应该把DST_ADDR部分改写为客户端的ADDR,
        但是在服务端处会直接获取本次连接的socketpeernema作为客户端地址,所以此处不对DST做处理"""
        req = await self.Loop.sock_recv(ACSocket, 4)
        VER,CMD,RSV,ATYP = req
        ConnectInfo["CMD"] = CMD
        #logging.debug("%s,%s,%s,%s"%(VER,CMD,RSV,ATYP))
        if VER != 5 or CMD not in (1,2,3) or \
        RSV != 0 or ATYP not in (1,3,4):
            ACSocket.close()
            return None
        if ATYP == 1:
            DST_ADDR_NUM = None
            ACSocket.setblocking(False)
            DST_ADDR = await self.Loop.sock_recv(ACSocket, 4)
            req += DST_ADDR
            #ConnectInfo["Host"] = socket.inet_ntop(socket.AF_INET, DST_ADDR)
            #ConnectInfo["Family"] = socket.AF_INET
        elif ATYP == 3:
            DST_ADDR_NUM = await self.Loop.sock_recv(ACSocket, 1)
            DST_ADDR = await self.Loop.sock_recv(ACSocket, struct.unpack('>B', DST_ADDR_NUM)[0])
            req += DST_ADDR_NUM+DST_ADDR
            #addr = await self.Loop.getaddrinfo(DST_ADDR.decode(),None)
            #ConnectInfo["Host"] = addr[0][4][0]
            #ConnectInfo["Family"] = addr[0][0]
        elif ATYP == 4:
            DST_ADDR_NUM = None
            DST_ADDR = await self.Loop.sock_recv(ACSocket, 16)
            req += DST_ADDR
            #ConnectInfo["Host"] = socket.inet_ntop(socket.AF_INET6, DST_ADDR)
            #ConnectInfo["Family"] = socket.AF_INET6
        DST_PORT = await self.Loop.sock_recv(ACSocket, 2)
        ConnectInfo["Port"] = struct.unpack('>H', DST_PORT)[0]
        req += DST_PORT
        #logging.debug("%s,%s"%(ConnectInfo["Host"],ConnectInfo["Port"]))
        return (req)

    async def GetFirstRequest(self,ConnectInfo, CSSocket):
        """获取第一次请求信息,直接使用socks5协议，不做额处理,
        需要完成ConnectInfo中CMD,Host,Port,Family字段的获取,TCP函数"""
        ConnectInfo["FirstRequestMethod"] = "socks5"
        #loop.sock_recv(Socket, 4) 并不能保证一定可以读入指定数量的内容
        ConnectInfo["VER"],ConnectInfo["CMD"],RSV,ConnectInfo["ATYP"] = await self.Loop.sock_recv(CSSocket, 4)
        if ConnectInfo["VER"] != 5 or ConnectInfo["CMD"] not in (1,2,3) or \
        RSV != 0 or ConnectInfo["ATYP"] not in (1,3,4):
            CSSocket.close()
            return None

        if ConnectInfo["ATYP"] == 1:
            ConnectInfo["DST_ADDR_NUM"] = None
            ConnectInfo["DST_ADDR"] =  await self.Loop.sock_recv(CSSocket, 4)
            ConnectInfo["Host"] = socket.inet_ntop(socket.AF_INET, ConnectInfo["DST_ADDR"])
            ConnectInfo["Family"] = socket.AF_INET
        elif ConnectInfo["ATYP"] == 3:
            ConnectInfo["DST_ADDR_NUM"] = await self.Loop.sock_recv(CSSocket, 1)
            ConnectInfo["DST_ADDR"] = await self.Loop.sock_recv(CSSocket, (struct.unpack('>B', ConnectInfo["DST_ADDR_NUM"])[0]))
            #[(<AddressFamily.AF_INET: 2>, 0, 0, '', ('14.215.177.37', 1000)),...]
            addr = await self.Loop.getaddrinfo(ConnectInfo["DST_ADDR"].decode(),None)
            ConnectInfo["Host"] = addr[0][4][0]
            ConnectInfo["Family"] = addr[0][0]
        elif ConnectInfo["ATYP"] == 4:
            ConnectInfo["DST_ADDR_NUM"] = None
            ConnectInfo["DST_ADDR"] = await self.Loop.sock_recv(CSSocket, 16)
            ConnectInfo["Host"] = socket.inet_ntop(socket.AF_INET6, ConnectInfo["DST_ADDR"])
            ConnectInfo["Family"] = socket.AF_INET6

        ConnectInfo["DST_PORT"] = await self.Loop.sock_recv(CSSocket, 2)
        ConnectInfo["Port"] = struct.unpack('>H', ConnectInfo["DST_PORT"])[0]
        return ConnectInfo

    def FirstResponse(self, DSSocket, ServerPublicAddress):
        """连接建立后对客户端的返回，
        此处直接按照socks5标准返回,TCP函数"""
        #BND为服务器对目标进行连接的地址或服务器的监听地址
        if DSSocket.family is socket.AF_INET:
            BND_ADDR, BND_PORT = DSSocket.getsockname()
        else:
            BND_ADDR, BND_PORT, flowinfo, scopeid = DSSocket.getsockname()
        BND_ADDR = ServerPublicAddress
        BND_ADDR = BND_ADDR.encode()
        BND_PORT = struct.pack('>H', BND_PORT)
        data = b'\x05\x00\x00' + b'\x03' + struct.pack('>B', len(BND_ADDR)) + BND_ADDR + BND_PORT
        return data

    async def GetFirstResponse(self, SCSocket):
        """返回解包,TCP函数"""
        FirstResponse = await self.Loop.sock_recv(SCSocket,4)
        if FirstResponse[3] == 1:
            FirstResponse += await self.Loop.sock_recv(SCSocket,6)
        elif FirstResponse[3] == 3:
            FirstResponse += await self.Loop.sock_recv(SCSocket,1)
            FirstResponse += await self.Loop.sock_recv(SCSocket,FirstResponse[4]+2)
        elif FirstResponse[3] == 4:
            FirstResponse += await self.Loop.sock_recv(SCSocket,18)
        return FirstResponse

    def SecondResponse(self, DSSocket):
        """在bind模式中，连接成功建立后还要再次返回一个包"""
        pass

    async def GetSecondResponse(self, SCSocket):
        """日后完善"""
        pass

    def FirstUDPResponse(self, USSocket, ServerBindAddr):
        """连接建立后对客户端的返回，
        此处直接按照socks5标准返回,Udp函数"""
        #BND为要求客户端进行连接的服务器地址,默认使用CSSocket端口作为UDP端口
        #BND_PORT = struct.pack('>H', ServerBindAddr[1])
        BND_ADDR = ServerBindAddr[0].encode()
        data = b'\x05\x00\x00' + b'\x03' + struct.pack('>B', len(BND_ADDR)) + BND_ADDR + struct.pack('>H', ServerBindAddr[1])
        return data

    async def GetFirstUDPResponse(self, SCSocket, ClientBindAddr):
        """返回解包,主要是要把服务器的BND换成客户端的BND,否则客户端会直接把数据发至服务器"""
        PerResponse = await self.Loop.sock_recv(SCSocket,4)
        if PerResponse[3] == 1:
            BNDResponse = await self.Loop.sock_recv(SCSocket,6)
        elif PerResponse[3] == 3:
            BND_ADDR_NUM = await self.Loop.sock_recv(SCSocket,1)
            BNDResponse = await self.Loop.sock_recv(SCSocket, struct.unpack('>B', BND_ADDR_NUM)[0]+2)
        elif PerResponse[3] == 4:
            BNDResponse = await self.Loop.sock_recv(SCSocket,18)
        self.ConnectInfo["UDPHost"] = BNDResponse[0:-2].decode()
        self.ConnectInfo["UDPPort"] = struct.unpack('>H', BNDResponse[-2:])[0]

        BND_ADDR = socket.inet_pton(socket.AF_INET, ClientBindAddr[0])
        return PerResponse[0:-1] + b'\x01' + BND_ADDR + struct.pack('>H', ClientBindAddr[1])

    def pack(self,data):
        """封包，返回完成后的数据流"""
        return data

    def unpack(self,data):
        """解包，接受一个非空二进制data，返回完成解析的数据和剩余的尚不完整的数据，
        若出错则返回None,后续程序将会关闭连接"""
        return (data,b"")

Packers = {
    "Origin":Pack
}