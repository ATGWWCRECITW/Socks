# Socks
一个简单的Socks5转发工具<br>
需要环境:<br>
python3.5 或以上<br>
pycryptodome [安装](http://pycryptodome.readthedocs.io/en/latest/src/installation.html)(注意是pycryptodome不是pycryptodomex)<br>
uvloop (直接pip install uvloop)(仅linux下的服务端需要)<br>
[关于asyncio+uvloop的并发性能](https://magic.io/blog/uvloop-blazing-fast-python-networking/)
<br>
##特性
* 单端口多用户
* 多线程工作(一个认证线程+n个转发线程)
* 二次开发认证和转发方法较为简便
* UDP/TCP/IPv4/IPv6流量统计
* 每用户下每地址连接统计
* 基于asyncio和uvloop,理论上有很强的并发能力
* 支持socks5 TCP connect和UDP ASSOCIATE(由于没用找到使用TCP bind模式的软件，暂时无法进行相关功能的开发)
* 客户端和服务端支持全平台
<br>
##使用
Client目录下
编辑ClientConfig.json<br>
<pre><code>
[
    {
        "Default":true, #设置为true即为选中该配置
        "ConfigName":"",#暂时没用
        "ServerAddress":"127.0.0.1",#设置服务端地址(可以是域名)
        "ServerPort":80,#设置服务端端口
        "ClientBindAddress":"0.0.0.0",#设置客户端监听地址
        "ClientPublicAddress":"localhost",#设置客户端地址(UDP模式下需要指明客户端地址,才能完成连接)
        "ClientPort":8800,#设置客户端监听端口
        "UserName":"testUser",#设置用户名
        "AuthMethod":"Origin",#设置认证方式
        "PackMethod":"Origin",#设置转发方法
        "Password":"testUser",#设置用户密码
        "Flow":{#此项目前没用
            "IPv4":{
                "Up":0,
                "Down":0
            },
            "IPv6":{
                "Up":0,
                "Down":0
            }
        }
    },
	...#其他配置
]
</code></pre>
Server目录下
编辑Config.json<br>
<pre><code>
{
    "ServerBindAddress":"0.0.0.0",#服务端监听地址
    "ServerPublicAddress":"127.0.0.1",#服务器地址(可以是域名)，这个设置非常重要，如有误，udp模式将无法正常工作
    "ServerPort":80,#服务端监听端口
    "UserListType":"Json",#暂时没用
    "AuthMethod":"Origin",#认证方法，所有进行连接的客户端都必须使用这个方法
    "UpdateInterval":300#统计数据刷新间隔(每5分钟刷新一次本地流量记录文件)
}
</code></pre>
编辑User.json<br>
<pre><code>
{
    "testUser": {#用户名
        "AuthMethod": "Origin",#认证方式，这个设置没用，以后可能会去掉
        "Password": "testUser",#用户密码
        "Flow": {#流量统计记录，服务端自己会维护，每次更新流量会加到原来的记录上
            "TCP": {
                "IPv4": {
                    "Up": 0,
                    "Down": 0
                },
                "IPv6": {
                    "Up": 0,
                    "Down": 0
                }
            },
            "UDP": {
                "IPv4": {
                    "Up": 0,
                    "Down": 0
                },
                "IPv6": {
                    "Up": 0,
                    "Down": 0
                }
            }
        },
        "Connection": 0,#连接数统计，这个设置没用，以后可能会去掉
        "MaxConnection": 100,#最大连接数，暂时还没有加这个功能
        "MaxSpeedPerConn": 10000#单连接最大速度，暂时还没有加这个功能
    }
}
</code></pre>
完成配置后
在Server目录下执行：python3 MSocksServer.py开启服务端<br>
在Client目录下执行：python3 MSocksClient.py开启客户端<br>
特别注意执行目录一定要在各自目录下,否则会提示找不到Mod中的pack和auth<br>

之后按照正常使用socks5代理的方法使用即可<br>

##服务端统计数据
