import time, asyncio, socket, sys, struct, logging, multiprocessing
from multiprocessing import reduction
from functools import partial
import Config
multiprocessing.allow_connection_pickling()
class SCProtocol(asyncio.Protocol):
    """用于SCsocket的处理，目标发送数据时，将其解包后传给客户端"""
    def __init__(self, ConnectInfo, ACtransport, ACprotocol, Packer):
        """ConnectInfo 是客户端连接时发送的请求信息，包含用户名，连接协议种类等信息，
        ACtransport 是客户端用于连接服务端的接口"""
        self.ACtransport = ACtransport
        self.ACprotocol = ACprotocol
        self.ConnectInfo = ConnectInfo
        self.Packer = Packer
        self.Data = b''

    def connection_made(self, transport):
        """CStransport在交由子进程loop管理后便暂停读取,
        当服务器到目标的连接建立后,把连接添加至CSProtocol中,
        再通过resume_reading恢复CStransport读取"""
        self.SCtransport = transport
        self.ACprotocol.SCtransport = transport
        
    def data_received(self, data):
        """测试，直接返回数据不处理"""
        self.Data += data

        data,self.Data = self.Packer.unpack(self.Data)
        self.ACtransport.write(data)

    def connection_lost(self, exc):
        """若断开连接，则断开客户端,应返回一些报错信息"""
        self.ACtransport.close()


class ACProtocol(asyncio.Protocol):
    """用于CtSsocket的处理，客户端发送数据时，将其解包后传给目标"""
    def __init__(self, ConnectInfo, Packer):
        """ConnectInfo 是客户端连接时发送的请求信息，包含用户名，连接协议种类等信息，
        StDtransport 是服务端用于目标的接口"""
        self.SCtransport = None
        self.ConnectInfo = ConnectInfo
        self.Packer = Packer

    def connection_made(self, transport):
        """CStransport在交由子进程loop管理后便暂停读取，
        当服务器到目标的连接建立后再通过DSProtocol类中的resume_reading恢复读取"""
        self.ACtransport = transport
        #无需返回信息

    def data_received(self, data):
        """发送数据至服务端"""
        self.SCtransport.write(self.Packer.pack(data))

    def connection_lost(self, exc):
        """若断开连接，则断开服务端,应返回一些报错信息"""
        if self.SCtransport is not None:
            self.SCtransport.close()


class UCProtocol(asyncio.Protocol):
    """"""
    def __init__(self, ConnectInfo, Packer, ACUtransport, AppAddr, ServerAddr):
        """接受客户端传来的连接，并通过UDP转发至服务端"""
        self.ConnectInfo = ConnectInfo
        self.Packer = Packer
        self.ServerAddr = ServerAddr
        self.AppAddr = AppAddr
        self.ACUtransport = ACUtransport

    def connection_made(self, transport):
        self.UCtransport = transport

    def datagram_received(self, Data, Addr):
        """判断来源再决定方向"""
        #print("datagram_received:",Data,Addr,self.ServerAddr,self.AppAddr)
        if Addr == self.ServerAddr:
            #解包
            Data,UseLess = self.Packer.unpack(Data)
            self.UCtransport.sendto(Data, self.AppAddr)
        elif Addr == self.AppAddr:
            #封包
            Data = self.Packer.pack(Data)
            self.UCtransport.sendto(Data, self.ServerAddr)

    def error_received(self, exc):
        logging.debug("UDP error_received:%s"%exc)
        self.ACUtransport.close()
        self.UCtransport.close()

class ACUProtocol(asyncio.Protocol):
    """用于在连接结束后关闭UPD通道,并上传流量"""
    def __init__(self):
        self.UCtransport = None
        self.SCtransport = None

    def connection_lost(self, exc):
        logging.debug("ACUProtocol Closed")
        if self.UCtransport is not None:
            self.UCtransport.close()
        if self.SCtransport is not None:
            self.SCtransport.close()