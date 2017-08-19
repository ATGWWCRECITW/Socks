import time, asyncio, socket, struct, logging, json
from multiprocessing import reduction
Config = json.load(open("Config.json"))
class DSProtocol(asyncio.Protocol):
    """用于StDsocket的处理，目标发送数据时，将其包装后传给客户端"""
    def __init__(self, Loop, ConnectInfo, Packer, TCPFlow, CStransport, CSprotocol):
        """ConnectInfo 是客户端连接时发送的请求信息，包含用户名，连接协议种类等信息，
        CtStransport 是客户端用于连接服务端的接口"""
        self.CStransport = CStransport
        self.CSprotocol = CSprotocol
        self.ConnectInfo = ConnectInfo
        self.TCPFlow = TCPFlow
        self.Packer = Packer
        self.Speed = 0
        self.MaxSpeed = ConnectInfo["User"]["MaxSpeedPerConn"]
        self.Loop = Loop
        self.ResetTask = None

    def connection_made(self, transport):
        """CStransport在交由子进程loop管理后便暂停读取(在TCPRely中),
        当服务器到目标的连接建立后,把连接添加至CSProtocol中,
        再通过resume_reading恢复CStransport读取"""
        self.DStransport = transport
        self.CSprotocol.DStransport = transport
        self.SocketType  = "IPv4" if transport.get_extra_info("socket").family == socket.AF_INET else "IPv6"
        self.ResetSpeed()

    def data_received(self, data):
        """向客户端送数据"""
        #是否应该避免从dict中频繁取数据
        data = self.Packer.pack(data)
        datalen = len(data)
        self.TCPFlow[self.SocketType]["Down"] += datalen
        self.CStransport.write(data)
        self.CheckSpeed(datalen)

    def connection_lost(self, exc):
        """若断开连接，则断开客户端,应返回一些报错信息"""
        #logging.debug("DSProtocol Closed")
        self.CStransport.close()
        if self.ResetTask is not None:
            self.ResetTask.cancel()

    def CheckSpeed(self, datalen):
        self.Speed += datalen
        if self.Speed >= self.MaxSpeed:
            #logging.debug("DSProtocol pause_reading")
            self.DStransport.pause_reading()

    def ResetSpeed(self):
        if self.Speed >= self.MaxSpeed:
            #logging.debug("DSProtocol resume_reading")
            self.DStransport.resume_reading()
        self.Speed = 0
        self.ResetTask = self.Loop.call_later(1, self.ResetSpeed)

class CSProtocol(asyncio.Protocol):
    """接收到客户端发送数据时，将其解包后传给目标"""
    def __init__(self, ConnectInfo, Packer, TCPFlow, OutPutFlowRecoder):
        """ConnectInfo 是客户端连接时发送的请求信息，包含用户名，连接协议种类等信息，
        StDtransport 是服务端用于目标的接口"""
        self.DStransport = None
        self.ConnectInfo = ConnectInfo
        self.Packer = Packer
        self.TCPFlow = TCPFlow
        self.Data = b''
        self.OutPutFlowRecoder = OutPutFlowRecoder

    def connection_made(self, transport):
        """CStransport在交由子进程loop管理后便暂停读取，
        当服务器到目标的连接建立后再通过DSProtocol类中的resume_reading恢复读取"""
        self.CStransport = transport
        self.Family  = "IPv4" if transport.get_extra_info("socket").family == socket.AF_INET else "IPv6"

    def data_received(self, data):
        """向目标发送数据"""
        self.TCPFlow[self.Family]["Up"] += len(data)
        self.Data += data
        data,self.Data = self.Packer.unpack(self.Data)
        self.DStransport.write(data)

    def connection_lost(self, exc):
        """若断开连接，则断开服务端,应返回一些报错信息"""
        #logging.debug("CSProtocol Closed")
        #回传流量
        self.OutPutFlowRecoder("TCP", self.TCPFlow, self.ConnectInfo)
        #关闭接口
        if self.DStransport is not None:
            self.DStransport.close()

class USProtocol(asyncio.Protocol):
    """考虑到支持IPV6/IPv4互相输出，可能需要另一个ipv6Socket"""
    def __init__(self, Loop, Packer, CSUtransport, UDPFlow, ClientAddr):
        """ConnectInfo 是客户端连接时发送的请求信息，包含用户名，连接协议种类等信息，
        StDtransport 是服务端用于目标的接口"""
        #self.ConnectInfo = ConnectInfo
        self.Packer = Packer
        self.UDPFlow = UDPFlow
        self.ClientAddr = ClientAddr
        self.CSUtransport = CSUtransport
        self.Loop = Loop
        self.MaxSpeed = ConnectInfo["User"]["MaxSpeedPerConn"]
        self.Speed = 0
        self.ResetTask = None

    def connection_made(self, transport):
        self.UStransport = transport
        self.Family = "IPv4" if transport.get_extra_info("socket").family == socket.AF_INET else "IPv6"
        self.ResetSpeed()
    def datagram_received(self, Data, Addr):
        """判断来源再决定方向"""
        if Addr == self.ClientAddr:
            #解包
            self.UDPFlow[self.Family]["Up"] += len(Data)
            Data,UseLess = self.Packer.unpack(Data)
            task = self.Loop.create_task(self.ResolveData(Data))
            task.add_done_callback(self.SendData)
        else:
            #封包
            Data = self.Packer.pack(Data)
            datalen = len(Data)
            self.UDPFlow[self.Family]["Down"] += datalen
            Data = self.AddHead(Addr, Data)
            self.UStransport.sendto(Data, self.ClientAddr)
            self.CheckSpeed(datalen)

    def error_received(self, exc):
        logging.debug("UDP error_received:%s"%exc)
        self.CSUtransport.close()
        self.UStransport.close()

    def SendData(self, future):
        Family, Addr, Data = future.result()
        if Data is not None:
            self.UStransport.sendto(Data, Addr)

    async def ResolveData(self, Data):
        """解析UPD请求,考虑用loop+回调解决"""
        print(Data)
        RSV1,RSV2,FRAG,ATYP = Data[0:4]
        #不接受需要重组排序的UDP数据
        if RSV1 == RSV2 == FRAG == 0:
            if ATYP == 1:
                Seek = 8
                DST_ADDR = Data[4:Seek]
                Host = socket.inet_ntop(socket.AF_INET, DST_ADDR)
                Family = socket.AF_INET
            elif ATYP == 3:
                DST_ADDR_NUM = Data[4:5]
                Seek = 5+DST_ADDR_NUM
                DST_ADDR = Data[5:Seek]
                #此处考虑用loop+回调
                #addr = socket.getaddrinfo(DST_ADDR.decode(),None)
                addr = await self.Loop.getaddrinfo(DST_ADDR.decode(),None)
                Host = addr[0][4][0]
                Family = addr[0][0]
            elif ATYP == 4:
                Seek = 20
                DST_ADDR = Data[4:Seek]
                Host = socket.inet_ntop(socket.AF_INET6, DST_ADDR)
                Family = socket.AF_INET6
            DST_PORT = Data[Seek:Seek+2]
            Port = struct.unpack('>H', DST_PORT)[0]
            return Family,(Host,Port),Data[Seek+2:]
        else:
            return None,None,None

    def AddHead(self, Addr, Data):
        Head = b'\x00\x00\x00'
        if self.Family == "IPv4":
            Head += b'\x01' + socket.inet_pton(socket.AF_INET, Addr[0])
        else:
            Head += b'\x04' + socket.inet_pton(socket.AF_INET6, Addr[0])
        Head += struct.pack('>H', Addr[1])
        return Head + Data

    def CheckSpeed(self, datalen):
        self.Speed += datalen
        if self.Speed >= self.MaxSpeed:
            #logging.debug("DSProtocol pause_reading")
            self.UStransport.pause_reading()

    def ResetSpeed(self):
        if self.Speed >= self.MaxSpeed:
            #logging.debug("DSProtocol resume_reading")
            self.UStransport.resume_reading()
        self.Speed = 0
        self.ResetTask = self.Loop.call_later(1, self.ResetSpeed)

class CSUProtocol(asyncio.Protocol):
    """用于在连接结束后关闭UPD通道,并上传流量"""
    def __init__(self, ConnectInfo, UDPFlow, OutPutFlowRecoder):
        self.USprotocol = None
        self.UDPFlow = UDPFlow
        self.OutPutFlowRecoder = OutPutFlowRecoder
        self.ConnectInfo = ConnectInfo

    def connection_lost(self, exc):
        #logging.debug("CSUProtocol Closed")
        if self.USprotocol is not None:
            self.USprotocol.close()
        self.OutPutFlowRecoder("UDP", self.UDPFlow, self.ConnectInfo)
