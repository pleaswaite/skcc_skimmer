#!/usr/bin/python
'''

   The MIT License (MIT)

   Copyright (c) 2015 Mark J Glenn

   Permission is hereby granted, free of charge, to any person obtaining a copy
   of this software and associated documentation files (the "Software"), to deal
   in the Software without restriction, including without limitation the rights
   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
   copies of the Software, and to permit persons to whom the Software is
   furnished to do so, subject to the following conditions:

   The above copyright notice and this permission notice shall be included in all
   copies or substantial portions of the Software.

   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
   SOFTWARE.

   Mark Glenn, March 2015
   mglenn@cox.net

'''
import socket
import select
import random
import time

from MJG import cSocketLoop 
from MJG import cStateMachine

K7MJG_EXTERNAL_IP = '68.99.90.75'
K7MJG_INTERNAL_IP = '192.168.0.100'

MASTER_BASE = 50000
SLAVE_BASE  = 60000

MasterClusterList = {
  'K7MJG': [
    (K7MJG_EXTERNAL_IP, SLAVE_BASE+0),
    (K7MJG_EXTERNAL_IP, SLAVE_BASE+1),
    (K7MJG_EXTERNAL_IP, SLAVE_BASE+2),
  ],

  'RBN': [
    ('telnet.reversebeacon.net',    7000),
    ('arcluster.reversebeacon.net', 7000),
    ('relay2.reversebeacon.net',    7000),
  ],

  ### Clusters Used for Testing ###

  'K7MJG_INTERNAL_SLAVE': [
    (K7MJG_INTERNAL_IP, SLAVE_BASE+0),
    (K7MJG_INTERNAL_IP, SLAVE_BASE+1),
    (K7MJG_INTERNAL_IP, SLAVE_BASE+2),
  ],

  'K7MJG_INTERNAL_MASTER': [
    (K7MJG_INTERNAL_IP, MASTER_BASE+0),
    (K7MJG_INTERNAL_IP, MASTER_BASE+1),
    (K7MJG_INTERNAL_IP, MASTER_BASE+2),
  ],

  'LOCALHOST_SLAVE': [
    ('127.0.0.1', SLAVE_BASE+0),
    ('127.0.0.1', SLAVE_BASE+1),
    ('127.0.0.1', SLAVE_BASE+2),
  ],

  'LOCALHOST_MASTER': [
    ('127.0.0.1', MASTER_BASE+0),
    ('127.0.0.1', MASTER_BASE+1),
    ('127.0.0.1', MASTER_BASE+2),
  ],
}


class cRBN:
  def __init__(self):
    self.bIncoming = b''
    self.bOutgoing = b''
   
    self.InactivityTimeoutSeconds = 60

  def Receive(self):
    try:
      bData = self.Socket.recv(4 * 1024)
    except socket.error:
      return False
    else:
      if not bData:
        return False

      self.bIncoming += bData
      return True

  def SentAll(self):
    try:
      BytesSent = self.Socket.send(self.bOutgoing)
      self.bOutgoing = self.bOutgoing[BytesSent:]
    except:
      self.Transition(self.STATE_Closing)
    else:
      return len(self.bOutgoing) == 0


class cRBN_Client(cRBN, cStateMachine):
  def __init__(self, SocketLoop, CallSign, Clusters):
    cRBN.__init__(self)
    cStateMachine.__init__(self, self.STATE_ConnectingToRBN, Debug = False)

    self.SocketLoop        = SocketLoop
    self.CallSign          = CallSign
    self.MasterClusterList = MasterClusterList
    self.Socket            = None
    self.Iter              = None
    self.AddressTuple      = None
    self.Cluster           = None
 
    if ',' in Clusters:
      self.Clusters = Clusters.upper().split(',')
    else: 
      self.Clusters = Clusters.upper().split()

  @staticmethod
  def FindEnd(What, String):
    Index = String.find(What)

    if Index == -1:
      return None

    return Index + len(String)

  def STATE_ConnectingToRBN(self):
    def ENTER():
      AddressTupleList = []

      for ClusterKey in self.Clusters:
        ServerList = self.MasterClusterList[ClusterKey]
        random.shuffle(ServerList)

        for AddressTuple in ServerList:
          AddressTupleList.append((ClusterKey, AddressTuple))

      self.Iter = iter(AddressTupleList)
      __Initiate()

    def CONNECTED():
      Address, Port = self.AddressTuple
      print('\nCONNECTED to {} ({}:{})... '.format(self.Cluster, Address, Port, self.Cluster))

      self.SocketLoop.RemoveConnector(self.Socket)
      self.Transition(self.STATE_WaitingForPrompt)

    def REFUSED():
      #print('Attempt to Connect to {} REFUSED... '.format(self.AddressTuple))
      self.SocketLoop.RemoveConnector(self.Socket)
      self.Socket.close()
      __Initiate()

    def TIMEOUT():
      #print('Attempt to Connect to {} TIMED OUT... '.format(self.AddressTuple))
      self.SocketLoop.RemoveConnector(self.Socket)
      self.Socket.close()
      __Initiate()

    def __Initiate():
      self.Cluster, self.AddressTuple = next(self.Iter, (None, None))

      if self.AddressTuple:
        self.Socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.Socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 0)
        self.Socket.setblocking(0)
        self.SocketLoop.AddConnector(self.Socket, self)

        while True:
          try:
            self.Socket.connect_ex(self.AddressTuple)
          except socket.error:
            print('\nNo apparent network connection.  Retrying...')
            time.sleep(1)
            continue
          else:
            self.TimeoutInSeconds(.250)
            break
      else:
        print('Failed to connect to any server.')
        self.Transition(self.STATE_PauseAndReconnect)

    return locals()

  def STATE_PauseAndReconnect(self):
    def ENTER():
      self.TimeoutInSeconds(1.5)

    def TIMEOUT():
      self.Transition(self.STATE_ConnectingToRBN)
      
    return locals() 

  def STATE_WaitingForPrompt(self):
    def ENTER():
      self.SocketLoop.AddReader(self.Socket, self)
      self.TimeoutInSeconds(15)

    def EXIT():
      self.SocketLoop.RemoveReader(self.Socket)

    def READY_TO_READ():
      if not self.Receive():
        self.Transition(self.STATE_Closing)
      else:
        if self.bIncoming == b'\xff\xfc\x22':
          ''' Special, strange prompt sequence from relay2 '''
          self.bIncoming = b''
          self.Transition(self.STATE_SendingCallSign)
        else:
          ''' Normal prompt '''
          End = cRBN_Client.FindEnd('call: ', self.bIncoming.decode('ascii'))

          if End:
            self.bIncoming = self.bIncoming[End:]
            self.Transition(self.STATE_SendingCallSign)
       

    def TIMEOUT():
      print('Timed out')
      self.Transition(self.STATE_Closing)

    return locals()

  def STATE_SendingCallSign(self):
    def ENTER():
      CallSign = self.CallSign + '\r\n'
      bCallSign = CallSign.encode('ascii')

      self.bOutgoing += bCallSign
      self.SocketLoop.AddWriter(self.Socket, self)

    def EXIT():
      self.SocketLoop.RemoveWriter(self.Socket)

    def READY_TO_WRITE():
      if self.SentAll():
        self.Transition(self.STATE_WaitingForHeader)

    return locals()

  def STATE_WaitingForHeader(self):
    def ENTER():
      self.SocketLoop.AddReader(self.Socket, self)
      self.TimeoutInSeconds(.75)

    def EXIT():
      self.SocketLoop.RemoveReader(self.Socket)

    def READY_TO_READ():
      if not self.Receive():
        self.Transition(self.STATE_Closing)
      else:
        End = cRBN_Client.FindEnd(b'>\r\n\r\n', self.bIncoming)

        if End:
          ''' Normal header. '''

          self.bIncoming = self.bIncoming[End:]
          self.Transition(self.STATE_ConnectedToRBN)
        else:
          ''' For some reason, relay2 is special. '''

          End = cRBN_Client.FindEnd(b"Welcome to RBN's bulk spots telnet server.\r\n", self.bIncoming)

          if End:
            self.bIncoming = self.bIncoming[End:]
            self.Transition(self.STATE_ConnectedToRBN)

    def TIMEOUT():
      self.Transition(self.STATE_Closing)

    return locals()

  def STATE_ConnectedToRBN(self):
    def ENTER():
      self.SocketLoop.AddReader(self.Socket, self)
      self.TimeoutInSeconds(self.InactivityTimeoutSeconds)

    def EXIT():
      self.SocketLoop.RemoveReader(self.Socket)

    def READY_TO_READ():
      self.TimeoutInSeconds(self.InactivityTimeoutSeconds)

      if not self.Receive():
        print('\nLost connection.  Attempting to reconnect...')
        self.Transition(self.STATE_PauseAndReconnect)
      else:
        self.RawData(self.bIncoming)
        self.bIncoming = b''

    def TIMEOUT():
      print('\nNo activity for {} seconds.  Attempting to reconnect.'.format(self.InactivityTimeoutSeconds))
      #self.Socket.shutdown(socket.SHUT_RDWR)
      #self.Socket.close()
      self.Transition(self.STATE_PauseAndReconnect)

    return locals()

  def STATE_Closing(self):
    def ENTER():   
      self.Socket.shutdown(socket.SHUT_RDWR)
      self.Socket.close()
      self.Transition(self.STATE_Closed)

    return locals()

  def STATE_Closed(self):
    def ENTER():   
      pass

    return locals()

  def RawData(self, bData):
    pass

