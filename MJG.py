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

   Mark Glenn, February 2015
   mglenn@cox.net

'''
import time
import errno

class cStateMachine:
  StateMachines = {}

  def __init__(self, InitialState, Debug = False):
    cStateMachine.StateMachines[self] = True

    self.Debug          = Debug
    self.Timeout        = None
    self.State          = None
    self.EventFunctions = {}
    self.InitialState   = InitialState

  def __CacheEventFunctions(self):
    if self.State not in self.EventFunctions:
      self.EventFunctions = self.State()

      if self.EventFunctions is None:
        print('Must return locals in {}'.format(State.__name__))
        return

  def SendEvent(self, Event):
    self.__CacheEventFunctions()

    if Event in self.EventFunctions:
      self.EventFunctions[Event]()

  def SendEventArg(self, Event, Arg):
    self.__CacheEventFunctions()

    if Event in self.EventFunctions:
      self.EventFunctions[Event](Arg)

  def Transition(self, To):
    if self.State != None:
      if self.Debug:
        print('<<< {}.{}...'.format(self.__class__.__name__, self.State.__name__))

      self.Timeout = None
      self.SendEvent('EXIT')

    self.State = To

    if self.Debug:
      print('>>> {}.{}...'.format(self.__class__.__name__, self.State.__name__))

    self.SendEvent('ENTER')

  def TimeoutInSeconds(self, Seconds):
    self.Timeout = time.time() + Seconds

  def Terminate(self):
    cStateMachine.StateMachines.pop(self)

  def Run(self):
   if self.State == None:
     self.Transition(self.InitialState)
   elif self.Timeout != None:
     if time.time() > self.Timeout:
       self.SendEvent('TIMEOUT')

  @staticmethod
  def RunAll():
    for StateMachine in cStateMachine.StateMachines:
      StateMachine.Run()


''' cSocketLoop
'''
import socket
import select

class cSocketLoop:
  def __init__(self, Timeout = .1, Debug = False):
    self.Timeout          = Timeout
    self.Debug            = Debug
    self.ReaderSockets    = {}
    self.WriterSockets    = {}
    self.ConnectorSockets = {}

  def AddReader(self, Socket, NotificationObject):
    self.ReaderSockets[Socket] = NotificationObject

  def RemoveReader(self, Socket):
    self.ReaderSockets.pop(Socket)

  def AddWriter(self, Socket, NotificationObject):
    self.WriterSockets[Socket] = NotificationObject

  def RemoveWriter(self, Socket):
    self.WriterSockets.pop(Socket)

  def AddConnector(self, Socket, NotificationObject):
    self.ConnectorSockets[Socket] = NotificationObject

  def RemoveConnector(self, Socket):
    self.ConnectorSockets.pop(Socket)

  def RunCount(self, Count):
    for I in range(0, Count):
      self.RunOne()

  def Run(self):
    while True:
      self.RunOne()

  def RunOne(self):
    cStateMachine.RunAll()

    AllWriters = list(self.WriterSockets) + list(self.ConnectorSockets)

    if len(self.ReaderSockets) + len(AllWriters) == 0:
      time.sleep(self.Timeout)
      return
  
    if self.Debug:
      if self.ReaderSockets:
        for ReaderSocket in self.ReaderSockets:
          print('WAITING TO READ: ', ReaderSocket)

      if self.WriterSockets:
        for WriterSocket in self.WriterSockets:
          print('WAITING TO WRITE:', self.WriterSockets)

      print('ReaderSockets: ', self.ReaderSockets)
      print('WriterSockets: ', AllWriters)

    ReadableSockets, WriteableSockets, ErrList = select.select(self.ReaderSockets, AllWriters, [], self.Timeout)

    for Socket in ReadableSockets:
      if self.Debug:
        print('READ READY:', Socket)

      self.ReaderSockets[Socket].SendEvent('READY_TO_READ')
      
    for Socket in WriteableSockets:
      if self.Debug:
        print('WRITE READY:', Socket)

      if Socket in self.WriterSockets:
        self.WriterSockets[Socket].SendEvent('READY_TO_WRITE')
      elif Socket in self.ConnectorSockets:
        Return = Socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)

        if Return == 0:
          self.ConnectorSockets[Socket].SendEvent('CONNECTED')
        elif Return == errno.ECONNREFUSED:
          self.ConnectorSockets[Socket].SendEvent('REFUSED')
