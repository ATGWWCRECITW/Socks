import asyncio, socket, logging, struct, json, time
from Crypto.Cipher import AES
from Crypto.Hash import MD5, SHA3_256
class auth(object):
    def __init__(self, ConnectInfo, Loop):
        """初始化时会传入连接信息"""
        self.ConnectInfo = ConnectInfo
        self.Loop = Loop

    def RequestAuth(self, SCSocket):
        """生成认证消息"""
        #            HEAD                |         Msg
        #nonce   UserNameLen  UserName   | Datalen Data   Mac
        #16bytes 1byte        Nbyte,N<255| 4byte   Nbyte  16byte
        ConnInfo = self.ConnectInfo["UserConfig"]
        UserName = ConnInfo["UserName"].encode()
        Key = self.GenerateKey(ConnInfo["Password"],digits=256)

        Cipher = AES.new(Key, AES.MODE_GCM, use_aesni=True)
        Head = Cipher.nonce + struct.pack('>B', len(UserName)) + UserName
        Cipher.update(Head)
        ServerAddress = SCSocket.getpeername()
        Msg = json.dumps({
            #ServerHost用于返回BND_ADDR
            "ServerHost":ServerAddress[0],
            "ServerPort":ServerAddress[1],
            "PackMethod":ConnInfo["PackMethod"],
            "Timestemp":time.time()
        })
        Data,Mac = Cipher.encrypt_and_digest(Msg.encode())
        Msg = struct.pack('>I', len(Data)) + Data + Mac
        SCSocket.send(Head + Msg)
        #如果return false则终止连接
        return True
    
    async def Auth(self, UserList, CSSocket):
        """验证登陆信息,返回包含UserName和PackMethod的字典"""
        #取nonce   UserNameLen
        PerHead = await self.Loop.sock_recv(CSSocket, 17)
        #取UserName   | Datalen
        PerData = await self.Loop.sock_recv(CSSocket, PerHead[16]+4)
        UserNameByte = PerData[0:PerHead[16]]
        UserName = UserNameByte.decode()
        if UserName in UserList:
            #取Data   Mac
            DataLen = int.from_bytes(PerData[PerHead[16]:],'big')
            DataMac = await self.Loop.sock_recv(CSSocket, DataLen+16)
            Key = self.GenerateKey(password=UserList[UserName]["Password"],digits=256)
            Cipher = AES.new(Key, AES.MODE_GCM, PerHead[0:16])
            Cipher.update(PerHead + UserNameByte)
            try:
                Msg = Cipher.decrypt_and_verify(DataMac[0:DataLen],DataMac[DataLen:])
                UserInfo = json.loads(Msg.decode())
                UserInfo["UserName"] = UserName
                if time.time() -UserInfo["Timestemp"] < 60:#1H
                    return UserInfo
            except ValueError as e:
                logging.info ("Key incorrect or message corrupted:%s"%e)
        return None

    def AuthFialed(self,CSSocket):
        """认证失败时的返回，可以返回404页面等，socket会在外部关闭，请不要在此处关闭"""
        pass

    def GenerateKey(self, password, digits=256):
        """生成256或128位摘要"""
        if digits == 256:
            h_obj = SHA3_256.new()
        elif digits == 128:
            h_obj = MD5.new()
        h_obj.update(password.encode())
        return h_obj.digest()


Authers = {
    "Origin":auth
}