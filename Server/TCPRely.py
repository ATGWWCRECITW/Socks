import asyncio, socket, sys, os, logging, multiprocessing, functools, json
from TCPServerProtocol import *
from pprint import pprint
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Mod import pack, auth
multiprocessing.allow_connection_pickling()
Config = json.load(open("Config.json"))
class ServerTcpRelyProcess(object):
    """在子线程中运行管理CtsSocket和StDSocket,
    建立连接并向客户端返回服务器连接信息，之后开始转发数据"""
    def __init__(self, Switch, Pipe):
        """Switch 是一个socket，每次传输1字节操作码,
        Pipe 为multiprocessing.Pipe()"""
        self.Switch = Switch
        self.Pipe = Pipe
        if sys.platform == 'win32':
            logging.info("Platform Detected win32, Use get_event_loop")
            self.Loop = asyncio.get_event_loop()
        elif sys.platform == 'linux':
            try:
                import uvloop
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            except Exception:
                logging.info("Platform Detected linux, Use get_event_loop")
                self.Loop = asyncio.get_event_loop()
            else: 
                logging.info("Platform Detected linux, Use uvloop")
                self.Loop = asyncio.get_event_loop()
        else:
            logging.info("Platform Detected Unknow, Use get_event_loop")
            self.Loop = asyncio.get_event_loop()
    
    def SwitchManager(self):
        """根据信号来对线程进行适当的操作，为了保证信息正确，应在本函数内完成信息的获取工作"""
        HandleCode = self.Switch.recv(1)
        if HandleCode == b'\x01':#接受新连接
            ConnectInfo = self.Pipe.recv()
            CSSocket = socket.fromfd(reduction.recv_handle(self.Pipe), ConnectInfo["AddressFamily"], ConnectInfo["SocketType"], ConnectInfo["SocketProto"])
            self.Loop.create_task(self.AddSocket(ConnectInfo, CSSocket))
            
    async def AddSocket(self, ConnectInfo, CSSocket):
        """初始化Protocol"""
        CSSocket.setblocking(False)
        ConnectInfo["ClientAddr"] = CSSocket.getpeername()
        #获取请求
        Packer = pack.Packers[ConnectInfo["AuthInfo"]["PackMethod"]](ConnectInfo, self.Loop)
        #获取第一次请求信息
        try:
            ConnectInfo = await asyncio.wait_for(fut=Packer.GetFirstRequest(ConnectInfo, CSSocket), timeout=Config["ConnectionTimeout"], loop=self.Loop)
        except ValueError as e:
            if "Request Code Value Error" in str(e):
                logging.debug("GetFirstRequest Failed: %s"%e)
                CSSocket.send(b'\x05\x01\x00\x01\x00\x00\x00\x00\x01')
                CSSocket.close()
                self.CallbackConnClose(ConnectInfo)
                return None
        except asyncio.TimeoutError as e:
            #X'01' general SOCKS server failure
            logging.debug("GetFirstRequest Timeout %s"%e)
            CSSocket.send(b'\x05\x01\x00\x01\x00\x00\x00\x00\x01')
            CSSocket.close()
            self.CallbackConnClose(ConnectInfo)
            return None
        Flow = {
            "UserName":ConnectInfo["AuthInfo"]["UserName"],
            "IPv4":{"Up":0,"Down":0},
            "IPv6":{"Up":0,"Down":0}
            }

        try:
            if ConnectInfo["CMD"] == 1:#connect
                #注意这里用大小写P来区分类和变量
                CStransport,CSprotocol = await self.Loop.connect_accepted_socket(lambda:CSProtocol(ConnectInfo, Packer, Flow, self.OutPutFlowRecoder), CSSocket)
                CStransport.pause_reading()
                create_conn = self.Loop.create_connection(lambda:DSProtocol(self.Loop, ConnectInfo, Packer, Flow, CStransport, CSprotocol), host=ConnectInfo["Host"], port=ConnectInfo["Port"])
                DStransport,DSprotocol = await asyncio.wait_for(fut=create_conn, timeout=Config["ConnectionTimeout"], loop=self.Loop)
                ConnectInfo["FirstResponse"] = Packer.FirstResponse(DStransport.get_extra_info('socket'), Config["ServerPublicAddress"])
                CStransport.write(ConnectInfo["FirstResponse"])
                CStransport.resume_reading()

            elif ConnectInfo["CMD"] == 2:#blind,socks5下客户端请求的blind只接受一次连接, 链接完成后server应被关闭, 关闭工作由CSprotocol完成
                logging.INFO("TCP bind Not Support yet")
                CStransport,CSprotocol = await self.Loop.connect_accepted_socket(lambda:CSProtocol(ConnectInfo, Packer, Flow, self.OutPutFlowRecoder), CSSocket)
                CStransport.pause_reading()
                TempServer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                TempServer.setblocking(False)
                TempServer.bind((self.Host,self.Port))
                TempServer.listen(1)
                CStransport.close()

            elif ConnectInfo["CMD"] == 3:#建立一个UDP服务器
                #添加CSSocket至Loop
                CSUtransport,CSUprotocol = await self.Loop.connect_accepted_socket(lambda:CSUProtocol(ConnectInfo, Flow, self.OutPutFlowRecoder), CSSocket)
                #建立UDP 不指定端口时系统会自动分配端口
                UStransport,USprotocol = await self.Loop.create_datagram_endpoint(lambda:USProtocol(self.Loop, Packer, CSUtransport, Flow, ClientAddr=CSSocket.getpeername()), local_addr=('0.0.0.0',0))
                CSUprotocol.UStransport = UStransport
                ConnectInfo["FirstUDPResponse"] = Packer.FirstUDPResponse(UStransport.get_extra_info('socket'), (Config["ServerPublicAddress"],UStransport.get_extra_info("socket").getsockname()[1]))
                CSUtransport.write(ConnectInfo["FirstUDPResponse"])

        except (TimeoutError,asyncio.TimeoutError) as e:
            #asyncio.TimeoutError和TimeoutError两种异常要区分开
            logging.debug("create_connection Timeout %s"%str(e))
            #这里使用了 X'04' Host unreachable 错误码
            CStransport.write(b'\x05\x04\x00\x01\x00\x00\x00\x00\x01')
            CStransport.close()
        except ConnectionRefusedError as e:
            logging.debug("create_connection refused %s"%str(e))
            CStransport.write(b'\x05\x05\x00\x01\x00\x00\x00\x00\x01')
            CStransport.close()
        except OSError as e:
            if "No route to host" in str(e):
                logging.debug("Addr:%s Host:%s Port:%s"%(ConnectInfo["DST_ADDR"],ConnectInfo["Host"], ConnectInfo["Port"]))
                logging.debug("create_connection Failed %s"%str(e))
                CStransport.write(b'\x05\x04\x00\x01\x00\x00\x00\x00\x01')
                CStransport.close()
        except socket.gaierror as e:
            if "Name or service not known" in str(e):
                logging.debug("Addr:%s Host:%s Port:%s"%(ConnectInfo["DST_ADDR"],ConnectInfo["Host"], ConnectInfo["Port"]))
                logging.debug("create_connection Failed %s"%str(e))
                CStransport.write(b'\x05\x04\x00\x01\x00\x00\x00\x00\x01')
                CStransport.close()
            
    def OutPutFlowRecoder(self, Type, Flow, ConnectInfo):
        """把流量数据回传回主线程,并通知主线程连接结束"""
        self.Pipe.send(Flow)
        self.Switch.send(b'\x02' if Type == "TCP" else b'\x03')
        self.CallbackConnClose(ConnectInfo)

    def CallbackConnClose(self, ConnectInfo):
        """通知主线程一个连接被关闭了"""
        self.Pipe.send({
            "UserName":ConnectInfo["AuthInfo"]["UserName"],
            "Addr":ConnectInfo["ClientAddr"][0]
        })
        self.Switch.send(b'\x04')

    def Run(self):
        """开启服务"""
        #uvloop接受fileno作为参数,而不是一个socket object，按开发者的话说这是python的一个bug?
        self.Loop.add_reader(self.Switch.fileno(),self.SwitchManager)
        try:
            self.Loop.run_forever()
        except KeyboardInterrupt as e:
            self.Stop()

    def Stop(self):
        """结束服务"""
        self.Loop.close()

class TcpConnAccepter(object):
    """接受客户端连接，并完成初始认证，和域名解析
    随后把socket交给后端建立连接并开始转发数据"""

    def __init__(self, Host, Port, ProcessList, Loop=None):
        """"OutPut是用来接受输出列表的函数"""
        self.Host = Host
        self.Port = Port
        self.ProcessList = ProcessList
        self.count = 0
        #根据平台选择loop类型
        if Loop is None:
            if sys.platform == 'win32':
                logging.info("Platform Detected win32, Use get_event_loop")
                self.Loop = asyncio.get_event_loop()
            elif sys.platform == 'linux':
                try:
                    import uvloop
                    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
                except Exception:
                    logging.info("Platform Detected linux,import uvloop Failed:%S Use get_event_loop"%e)
                    self.Loop = asyncio.get_event_loop()
                else: 
                    logging.info("Platform Detected linux, Use uvloop")
                    self.Loop = asyncio.get_event_loop()
            else:
                logging.info("Platform Detected Unknow, Use get_event_loop")
                self.Loop = asyncio.get_event_loop()
        else:
             self.Loop = Loop
        #设置服务器
        self.Server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.Server.setblocking(False)
        self.Server.bind((self.Host,self.Port))
        self.Server.listen(1024)
        self.UserList = dict()
        self.Connection = dict()

    def Accepter(self):
        """完成用户认证"""
        CtSSocket,addr = self.Server.accept()
        logging.debug("Author Connect from %r" % (addr,))
        ConnectInfo = {"AddressFamily":CtSSocket.family,
                        "SocketType":CtSSocket.type,
                        "SocketProto":CtSSocket.proto}
        #认证部分
        task = self.Loop.create_task(self.CompleteAuth(CtSSocket, ConnectInfo))
        task.add_done_callback(functools.partial(self.OutPut, CtSSocket, ConnectInfo))

    def Run(self):
        """开启服务"""
        self.UserListKeeper(self.UpdateUserConfigList)
        self.Loop.add_reader(self.Server.fileno(),self.Accepter)
        for ProcessManager in self.ProcessList:
            self.Loop.add_reader(ProcessManager["Handle"].fileno(), functools.partial(self.HandleManager, Handle=ProcessManager["Handle"], Pipe=ProcessManager["PPipe"]))
        logging.info("Server Started")
        self.Loop.run_forever()

    def Stop(self):
        """结束服务"""
        #阻塞关闭
        logging.info("Server Closed")
        self.Server.setblocking(True)
        self.Server.close()
        self.Loop.close()

    async def CompleteAuth(self, CSSocket, ConnectInfo):
        """调用自定义的auth类完成认证工作，因为抛异常在后面在完成回调中不易处理，此处如果发生错误就直接返回None"""
        Auther = auth.Authers[Config["AuthMethod"]](ConnectInfo, self.Loop)
        try:
            ConnectInfo["AuthInfo"] = await asyncio.wait_for(Auther.Auth(self.UserList, CSSocket), timeout=2, loop=self.Loop)
        except asyncio.TimeoutError as e:
            logging.debug("CompleteAuth TimeOut")
            ConnectInfo["AuthInfo"] = None
        except Exception as e:
            logging.debug(e)
            ConnectInfo["AuthInfo"] = None
        finally:
            return ConnectInfo

    def OutPut(self, CSSocket, ConnectInfo, CompleteAuth):
        """输出Socket,完成Connection计数"""
        #装作负载均衡
        ConnectInfo = CompleteAuth.result()
        if ConnectInfo["AuthInfo"] is not None:
            logging.debug("Auth Completed")
            self.count = (self.count+1)%len(self.ProcessList)
            ProcessManager = self.ProcessList[self.count]
            #计数
            UserName = ConnectInfo["AuthInfo"]["UserName"]
            ConnectInfo["User"] = self.UserList[UserName]
            
            ProcessManager["PPipe"].send(ConnectInfo)
            #linux下传递handel不需要pid
            reduction.send_handle(ProcessManager["PPipe"], CSSocket.fileno(), ProcessManager["Process"].pid)
            ProcessManager["Handle"].send(b'\x01')
            try:
                self.Connection[UserName]["ConnNum"] += 1
                try:
                    self.Connection[UserName][CSSocket.getpeername()[0]] += 1
                except KeyError:
                    self.Connection[UserName][CSSocket.getpeername()[0]] = 1
            except KeyError:
                self.Connection[UserName] = {"ConnNum":1,CSSocket.getpeername()[0]:1}
        else:
            CSSocket.close()

    def HandleManager(self, Handle, Pipe):
        """根据信号来对线程进行适当的操作，为了保证信息正确，应在本函数内完成信息的获取工作"""
        HandleCode = Handle.recv(1)
        if HandleCode == b'\x02':#回传TCP流量
            TCPFlow = Pipe.recv()
            OldTCPFlow = self.UserList[TCPFlow["UserName"]]["Flow"]["TCP"]
            OldTCPFlow["IPv4"]["Up"] += TCPFlow["IPv4"]["Up"]
            OldTCPFlow["IPv4"]["Down"] += TCPFlow["IPv4"]["Down"]
            OldTCPFlow["IPv6"]["Up"] += TCPFlow["IPv6"]["Up"]
            OldTCPFlow["IPv6"]["Down"] += TCPFlow["IPv6"]["Down"]
        elif HandleCode == b'\x03':#回传UDP流量
            UPDFlow = Pipe.recv()
            OldUPDFlow = self.UserList[UPDFlow["UserName"]]["Flow"]["TCP"]
            OldUPDFlow["IPv4"]["Up"] += UPDFlow["IPv4"]["Up"]
            OldUPDFlow["IPv4"]["Down"] += UPDFlow["IPv4"]["Down"]
            OldUPDFlow["IPv6"]["Up"] += UPDFlow["IPv6"]["Up"]
            OldUPDFlow["IPv6"]["Down"] += UPDFlow["IPv6"]["Down"]
        elif HandleCode == b'\x04':#关闭连接
            ConnInfo = Pipe.recv()
            UserName = ConnInfo["UserName"]
            self.Connection[UserName]["ConnNum"] -= 1
            if self.Connection[UserName][ConnInfo["Addr"]] == 1:
                del self.Connection[UserName][ConnInfo["Addr"]]
            else:
                self.Connection[UserName][ConnInfo["Addr"]] -= 1

    def UserListKeeper(self, Updater):
        """负责定期更新UserList中的Config,保存Flow并安排下一次更新"""
        self.UserList = Updater()
        self.Loop.call_later(Config["UpdateInterval"], self.UserListKeeper, Updater)

    def UpdateUserConfigList(self):
        """维护UserList中Config的内容，但不包含Flow的内容,UserList应包含的基本信息见User.json"""
        #读取新配置
        UserConfigList = json.load(open("User.json","r"))

        #把流量迁移到新的设置上,注意初次启动，删除旧用户和启用新用户时的处理
        #向文件记录中追加流量
        for K, V in UserConfigList.items():
            Flow = self.UserList.get(K, {}).get("Flow", {"TCP":{"IPv4":{"Up":0,"Down":0},"IPv6":{"Up":0,"Down":0}},"UDP":{"IPv4":{"Up":0,"Down":0},"IPv6":{"Up":0,"Down":0}}})
            V["Flow"]["TCP"]["IPv4"]["Up"] += Flow["TCP"]["IPv4"]["Up"]
            V["Flow"]["TCP"]["IPv4"]["Down"] += Flow["TCP"]["IPv4"]["Down"]
            V["Flow"]["TCP"]["IPv6"]["Up"] += Flow["TCP"]["IPv6"]["Up"]
            V["Flow"]["TCP"]["IPv6"]["Down"] += Flow["TCP"]["IPv6"]["Down"]
            V["Flow"]["UDP"]["IPv4"]["Up"] += Flow["UDP"]["IPv4"]["Up"]
            V["Flow"]["UDP"]["IPv4"]["Down"] += Flow["UDP"]["IPv4"]["Down"]
            V["Flow"]["UDP"]["IPv6"]["Up"] += Flow["UDP"]["IPv6"]["Up"]
            V["Flow"]["UDP"]["IPv6"]["Down"] += Flow["UDP"]["IPv6"]["Down"]

        with open("User.json","w+") as UserConfig:
            #这次写入用来更新文件中的流量
            UserConfig.seek(0)
            json.dump(UserConfigList, UserConfig, indent="    ")

        #本地流量从新开始统计
        for V in UserConfigList.values():
            V["Flow"] =  {"TCP":{"IPv4":{"Up":0,"Down":0},"IPv6":{"Up":0,"Down":0}},"UDP":{"IPv4":{"Up":0,"Down":0},"IPv6":{"Up":0,"Down":0}}}

        logging.info(self.Connection)
        return UserConfigList