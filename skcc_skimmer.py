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
#
# skcc_skimmer.py 
#
# Version 3.5.2, May 13, 2015
# 
# A program that uses the Reverse Beacon Network (RBN)
# to locate unique, unworked SKCC members for the purpose of 
# attaining SKCC award levels. 
#

#
# Contact: mark@k7mjg.com
#

#
# Quickstart: 
#
#  1. Make sure that you have Python installed.
#
#  2. Prepare an ADI logfile with stations worked thus far.
#
#  3. Run this utility from the command line with Python.
#
#     python skcc_skimmer.py [-c your-call-sign] [-a AdiFile] [-g "GoalString"] [-t "TargetString"] [-v]
#
#       The callsign is required unless you've specified MY_CALLSIGN in the skcc_skimmer.cfg file.
#
#       The ADI file is required unless you've specified ADI_FILE in the skcc_skimmer.cfg file.
#
#       GoalString: Any or all of: C,T,S,CXN,TXN,SXN,WAS,WAS-C,ALL,NONE. 
#
#       TargetString: Any or all of: C,T,S,CXN,TXN,SXN,ALL,NONE. 
#
#         (You must specify at least one GOAL or TARGET.)
#

#
# Portability:
#
#   This script has been tested on:
#
#   - Windows, ActiveState Python Versions 2.7.8 and 3.4.1.
#     (https://www.python.org/downloads/)
#
#   - Mac OS X, python 2.7.6.
#     (Preinstalled)
#
#   - Raspberry Pi, python 2.7.3 and 3.2.3
#     (Preinstalled)
#

from __future__ import division
import signal
import time
import sys
import os
import socket
import re
import getopt
import textwrap
import datetime
import calendar

from MJG import cSocketLoop
from MJG import cStateMachine

from RBN import cRBN_Client

from math import radians, sin, cos, atan2, sqrt


def SplitCommaSpace(String):
  if ',' in String:
    return [x.strip() for x in String.split(',')]

  return String.split()

def SplitWidths(String, Widths):
  List = []

  for Width in Widths:
    List.append(String[:Width])
    String = String[Width:]

  return List

def Effective(Date):
  TodayGMT = time.strftime('%Y%m%d000000', time.gmtime())

  if TodayGMT >= Date:
    return Date

  return ''

def Stripped(String):
  return ''.join([c for c in String if 31 < ord(c) < 127])

class cFastDateTime:
  MonthNames = 'January February March April May June July August September October November December'.split()

  def __init__(self, Object):
    if isinstance(Object, datetime.datetime):
      self.FastDateTime = Object.strftime('%Y%m%d%H%M%S')

    elif isinstance(Object, time.struct_time):
      self.FastDateTime = time.strftime('%Y%m%d%H%M%S', Object)

    elif isinstance(Object, tuple):
      if len(Object) == 3:
        Year, Month, Day = Object
        self.FastDateTime = '{:0>4}{:0>2}{:0>2}000000'.format(Year, Month, Day)
      elif len(Object) == 6:
        Year, Month, Day, Hour, Minute, Second = Object
        self.FastDateTime = '{:0>4}{:0>2}{:0>2}{:0>2}{:0>2}{:0>2}'.format(Year, Month, Day, Hour, Minute, Second)

    else:
      self.FastDateTime = Object

  def SplitDateTime(self):
    List = []
    String = self.FastDateTime

    for Width in (4, 2, 2, 2, 2, 2):
      List.append(int(String[:Width]))
      String = String[Width:]
  
    return List

  def StartOfMonth(self):
    Year, Month, Day, Hour, Minute, Second = self.SplitDateTime()
    return cFastDateTime('{:0>4}{:0>2}{:0>2}000000'.format(Year, Month, 1))

  def EndOfMonth(self):
    Year, Month, Day, Hour, Minute, Second = self.SplitDateTime()
    _, DaysInMonth = calendar.monthrange(Year, Month)
    return cFastDateTime('{:0>4}{:0>2}{:0>2}235959'.format(Year, Month, DaysInMonth))

  def Year(self):
    return int(self.FastDateTime[0:4])

  def Month(self):
    return int(self.FastDateTime[4:6])

  def ToDateTime(self):
    return datetime.datetime.strptime(self.FastDateTime, '%Y%m%d%H%M%S')

  def FirstWeekdayAfterDate(self, TargetWeekday):
    TargetWeekdayNumber = time.strptime(TargetWeekday, '%a').tm_wday
    DateTime = self.ToDateTime()

    while True:
      DateTime += datetime.timedelta(days=1)

      if DateTime.weekday() == TargetWeekdayNumber:
        return cFastDateTime(DateTime)

  def __repr__(self):
    return self.FastDateTime

  def __lt__(self, Right):
    return self.FastDateTime < Right.FastDateTime

  def __le__(self, Right):
    return self.FastDateTime <= Right.FastDateTime

  def __gt__(self, Right):
    return self.FastDateTime > Right.FastDateTime

  def __add__(self, Delta):
    return cFastDateTime(self.ToDateTime() + Delta)

  @staticmethod
  def NowGMT():
    return cFastDateTime(time.gmtime())


class cDisplay(cStateMachine):
  def __init__(self):
    cStateMachine.__init__(self, self.STATE_Running, Debug = False)
    self.DotsOutput = 0
    self.Run()

  def STATE_Running(self):
    def ENTER():
      if PROGRESS_DOTS['ENABLED']:
        self.TimeoutInSeconds(PROGRESS_DOTS['DISPLAY_SECONDS'])

    def PRINT(String):
      if self.DotsOutput > 0:
        print('')

      String = Stripped(String)
      print(String)
      self.DotsOutput = 0

      if PROGRESS_DOTS['ENABLED']:
        self.TimeoutInSeconds(PROGRESS_DOTS['DISPLAY_SECONDS'])

    def TIMEOUT():
      sys.stdout.write('.')
      sys.stdout.flush()
      self.DotsOutput += 1

      if self.DotsOutput > PROGRESS_DOTS['DOTS_PER_LINE']:
        print('')
        self.DotsOutput = 0 

      if PROGRESS_DOTS['ENABLED']:
        self.TimeoutInSeconds(PROGRESS_DOTS['DISPLAY_SECONDS'])
    
    return locals()

  def Print(self, String = ''):
    self.SendEventArg('PRINT', String)

class cHTTP:
  def __init__(self, Host, Port = 80):
    self.Socket  = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.bHost   = Host.encode('ascii')
    self.Port    = Port

  def Get(self, Page):
    try:
      self.Socket.connect((self.bHost, self.Port))
    except socket.error:
      print('No apparent network connection.')
      sys.exit(16)

    GetCommand  = 'GET {} HTTP/1.0\n\n'.format(Page)
    bGetCommand = GetCommand.encode('ascii')
    self.Socket.send(bGetCommand)

    bResponse = b''

    while True:
      bBuffer = self.Socket.recv(4096)

      if not bBuffer:
        break

      bResponse += bBuffer

    self.Socket.close()

    bHeader, bBody = bResponse.split(b'\r\n\r\n', 1)
    return bBody

def Beep():
  sys.stdout.write('\a')
  sys.stdout.flush()


class cSked(cStateMachine):
  RegEx = re.compile('<span class="callsign">(.*?)<span>(?:.*?<span class="userstatus">(.*?)</span>)?')

  def __init__(self):
    cStateMachine.__init__(self, self.STATE_Running, Debug = False)
    self.SkedSite = None
    self.PreviousLogins = {} 
    self.FirstPass = True

  def STATE_Running(self):
    def Common():
      self.DisplayLogins()
      self.TimeoutInSeconds(SKED['CHECK_SECONDS'])

    def ENTER():
      Common()

    def TIMEOUT():
      Common()
     
    return locals()

  def DisplayLogins(self):
    self.SkedSite = cHTTP('www.obriensweb.com')
    bContent      = self.SkedSite.Get('http://www.obriensweb.com/sked/index.php?board=skcc&frame=sidebar')
    Content       = bContent.decode('utf-8', 'ignore')
    SkedLogins    = cSked.RegEx.findall(Content)

    SkedHit = {}

    for CallSign, Status in SkedLogins:
      if CallSign == MY_CALLSIGN:
        continue

      CallSign = SKCC.ExtractCallSign(CallSign)

      if not CallSign:
        continue

      if CallSign in EXCLUSIONS:
        continue

      Report = [BuildMemberInfo(CallSign)]

      if CallSign in RBN.LastSpotted:
        fFrequency, StartTime = RBN.LastSpotted[CallSign]

        Now = time.time()
        DeltaSeconds = max(int(Now - StartTime), 1)

        if DeltaSeconds > 60 * 60:
          del RBN.LastSpotted[CallSign]
        elif DeltaSeconds > 60:
          DeltaMinutes = DeltaSeconds // 60
          Units = 'minutes' if DeltaMinutes > 1 else 'minute'
          Report.append('Last spotted {} {} ago on {}'.format(DeltaMinutes, Units, fFrequency))
        else:
          Units = 'seconds' if DeltaSeconds > 1 else 'second'
          Report.append('Last spotted {} {} ago on {}'.format(DeltaSeconds, Units, fFrequency))

      GoalList = QSOs.GetGoalHits(CallSign)

      if GoalList:
        Report.append('YOU need them for {}'.format(','.join(GoalList)))

      TargetList = QSOs.GetTargetHits(CallSign)

      if TargetList:
        Report.append('THEY need you for {}'.format(','.join(TargetList)))

      IsFriend = CallSign in FRIENDS

      if IsFriend:
        Report.append('friend')

      if Status:
        Report.append('STATUS: {}'.format(Stripped(Status)))

      if TargetList or GoalList or IsFriend:
        SkedHit[CallSign] = Report

    if SkedHit:
      GMT = time.gmtime()
      ZuluTime = time.strftime('%H%MZ', GMT)
      ZuluDate = time.strftime('%Y-%m-%d', GMT)

      if self.FirstPass:
        NewLogins = []
        self.FirstPass = False
      else:
        NewLogins = list(set(SkedHit)-set(self.PreviousLogins))

      self.PreviousLogins = SkedHit

      Display.Print('=========== SKCC Sked Page ============')
      for CallSign in sorted(SkedHit):
        if CallSign in NewLogins:
          if NOTIFICATION['ENABLED']:
            if (GoalList and 'goals' in BeepCondition) or (TargetList and 'targets' in BeepCondition):
              Beep()

          NewIndicator = '+'
        else:
          NewIndicator = ' '

        Out = '{}{}{:<6} {}'.format(ZuluTime, NewIndicator, CallSign, '; '.join(SkedHit[CallSign]))
        Display.Print(Out)
        Log('{} {}'.format(ZuluDate, Out))
      Display.Print('=======================================')

class cRBN_Filter(cRBN_Client):
  Zulu_RegEx = re.compile(r'^([01]?[0-9]|2[0-3])[0-5][0-9]Z$')
  dB_RegEx   = re.compile(r'^\s{0,1}\d{1,2} dB$')

  def __init__(self, SocketLoop, CallSign, Clusters):
    cRBN_Client.__init__(self, SocketLoop, CallSign, Clusters)
    self.bData = b''
    self.LastSpotted = {}
    self.Notified = {}
    self.RenotificationDelay = NOTIFICATION['RENOTIFICATION_DELAY_SECONDS']

  def RawData(self, bData):
    self.bData += bData

    while b'\r\n' in self.bData:
      bLine, self.bData = self.bData.split(b'\r\n', 1)
      Line = bLine.decode('ascii')
      self.HandleSpot(Line)

  @staticmethod
  def ParseSpot(Line):
    ''' If the line isn't exactly 75 characters, something is wrong. 
    '''
    if len(Line) != 75:   
      LogError(Line)
      return None

    if not Line.startswith('DX de '):
      LogError(Line)
      return None

    Spotter, Frequency = Line[6:24].split('-#:')

    Frequency = Frequency.lstrip()
    CallSign  = Line[26:35].rstrip()
    dB        = Line[47:49].strip()
    Zulu      = Line[70:75]
    CW        = Line[41:47].rstrip()
    Beacon    = Line[62:68].rstrip()

    if CW != 'CW':
      return None

    if Beacon == 'BEACON':
      return None

    if not cRBN_Filter.Zulu_RegEx.match(Zulu):
      LogError(Line)
      return None

    if not cRBN_Filter.dB_RegEx.match(Line[47:52]):
      LogError(Line)
      return None

    try:
      WPM = int(Line[53:56])
    except ValueError:
      LogError(Line)
      return None

    try:
      fFrequency = float(Frequency)
    except ValueError:
      LogError(Line)
      return None

    if '/' in CallSign:
      CallSign, _ = CallSign.split('/', 1)

    return Zulu, Spotter, fFrequency, CallSign, dB, WPM

  def HandleNotification(self, CallSign, GoalList, TargetList):
    NotificationFlag = ' '

    Now = time.time()

    for Call in dict(self.Notified):
      if Now > self.Notified[Call]:
        del self.Notified[Call]

    if CallSign not in self.Notified:
      if NOTIFICATION['ENABLED']:
        if (GoalList and 'goals' in BeepCondition) or (TargetList and 'targets' in BeepCondition):
          Beep()

      NotificationFlag = '+'
      self.Notified[CallSign] = Now + self.RenotificationDelay

    return NotificationFlag

  def HandleSpot(self, Line):
    if VERBOSE:
      print('   {}'.format(Line))

    Spot = cRBN_Filter.ParseSpot(Line)

    if not Spot:
      return

    Zulu, Spotter, fFrequency, CallSign, dB, WPM = Spot
  
    Report = []

    #-------------

    CallSign = SKCC.ExtractCallSign(CallSign)

    if not CallSign:
      return

    if CallSign in EXCLUSIONS:
      return

    #-------------

    if not IsInBANDS(fFrequency):
      return

    #-------------
  
    SpottedNearby = Spotter in SPOTTERS_NEARBY
  
    if SpottedNearby or CallSign == MY_CALLSIGN:
      if Spotter in Spotters:
        Miles = Spotters.GetDistance(Spotter)
        Report.append('by {}({}mi, {}dB)'.format(Spotter, Miles, int(dB)))
      else:
        Report.append('by {}({}dB)'.format(Spotter, int(dB)))

    #-------------

    You = CallSign == MY_CALLSIGN
 
    if You:
      Report.append('(you)')

    #-------------
  
    OnFrequency = cSKCC.IsOnSkccFrequency(fFrequency, OFF_FREQUENCY['TOLERANCE'])
  
    if not OnFrequency:
      if OFF_FREQUENCY['ACTION'] == 'warn':
        Report.append('OFF SKCC FREQUENCY!')
      elif OFF_FREQUENCY['ACTION'] == 'suppress':
        return

    #-------------

    if HIGH_WPM['ACTION'] == 'always-display':
      Report.append('{} WPM'.format(WPM))
    else:
      if WPM >= HIGH_WPM['THRESHOLD']:
        if HIGH_WPM['ACTION'] == 'warn':
          Report.append('{} WPM!'.format(WPM))
        elif HIGH_WPM['ACTION'] == 'suppress':
          return

    #-------------

    IsFriend = CallSign in FRIENDS

    if IsFriend:
      Report.append('friend')

    #-------------

    GoalList = QSOs.GetGoalHits(CallSign, fFrequency)

    if GoalList:
      Report.append('YOU need them for {}'.format(','.join(GoalList)))

    #-------------

    TargetList = QSOs.GetTargetHits(CallSign)
  
    if TargetList:
      Report.append('THEY need you for {}'.format(','.join(TargetList)))

    #-------------

    if (SpottedNearby and (GoalList or TargetList)) or You or IsFriend:
      RBN.LastSpotted[CallSign] = (fFrequency, time.time())

      ZuluDate = time.strftime('%Y-%m-%d', time.gmtime())

      FrequencyString = '{0:.1f}'.format(fFrequency)
      MemberInfo = BuildMemberInfo(CallSign)
  
      NotificationFlag = self.HandleNotification(CallSign, GoalList, TargetList)

      '''
      Now = time.time()

      for Call in dict(self.Notified):
        if Now > self.Notified[Call]:
          del self.Notified[Call]

      if CallSign not in self.Notified:
        if NOTIFICATION['ENABLED']:
          if (GoalList and 'goals' in BeepCondition) or (TargetList and 'targets' in BeepCondition):
            Beep()

        NotificationFlag = '+'
        self.Notified[CallSign] = Now + self.RenotificationDelay
      '''

      Out = '{}{}{:<6} {} on {:>8} {}'.format(Zulu, NotificationFlag, CallSign, MemberInfo, FrequencyString, '; '.join(Report))
  
      Display.Print(Out)
      Log('{} {}'.format(ZuluDate, Out))


class cQSO(cStateMachine):
  Prefix_RegEx = re.compile(r'([0-9]*[a-zA-Z]+\d+)')

  def __init__(self):
    cStateMachine.__init__(self, self.STATE_Running, Debug = False)
    self.QSOs = []

    self.Brag               = {}
    self.ContactsForC       = {}
    self.ContactsForT       = {}
    self.ContactsForS       = {}
    self.ContactsForWAS     = {}
    self.ContactsForWAS_C   = {}
    self.ContactsForP       = {}
    self.QSOsByMemberNumber = {}

    self.ReadQSOs()

    self.RefreshPeriodSeconds = 3

    MyMemberEntry       = SKCC.Members[MY_CALLSIGN]
    self.MyJoin_Date    = Effective(MyMemberEntry['join_date'])
    self.MyC_Date       = Effective(MyMemberEntry['c_date'])
    self.MyT_Date       = Effective(MyMemberEntry['t_date'])
    self.MyS_Date       = Effective(MyMemberEntry['s_date'])
    self.MyTX8_Date     = Effective(MyMemberEntry['tx8_date'])

    self.MyMemberNumber = MyMemberEntry['plain_number']

  def STATE_Running(self):
    def ENTER():
      self.TimeoutInSeconds(self.RefreshPeriodSeconds)

    def TIMEOUT():
      if os.path.getmtime(ADI_FILE) != self.AdiFileReadTimeStamp:
        QSOs.Refresh()
        Display.Print("'{}' file is changing. Waiting for write to finish...".format(ADI_FILE))

        ''' Once we detect the file has changed, we can't necessarily read it 
            immediately because the logger may still be writing to it, so we wait
            until the write is complete.
        '''
        while True:
          Size = os.path.getsize(ADI_FILE)
          time.sleep(1)

          if os.path.getsize(ADI_FILE) == Size:
            break


      self.TimeoutInSeconds(self.RefreshPeriodSeconds)
    
    return locals()

  def AwardsCheck(self):
    C_Level = len(self.ContactsForC)  // Levels['C']
    T_Level = len(self.ContactsForT)  // Levels['T']
    S_Level = len(self.ContactsForS)  // Levels['S']
    P_Level = self.CalcPrefixPoints() // Levels['P']

    ### C ###

    if self.MyC_Date:
      Award_C_Level = SKCC.CenturionLevel[self.MyMemberNumber]

      if C_Level > Award_C_Level:
        C_or_Cx = 'C' if Award_C_Level == 1 else 'Cx{}'.format(Award_C_Level)
        print('FYI: You qualify for Cx{} but have only applied for {}.'.format(C_Level, C_or_Cx))
    else:
      if C_Level == 1 and self.MyMemberNumber not in SKCC.CenturionLevel:
        print('FYI: You qualify for C but have not yet applied for it.')
 
    ### T ###

    if self.MyT_Date:
      Award_T_Level = SKCC.TribuneLevel[self.MyMemberNumber]

      if T_Level > Award_T_Level:
        T_or_Tx = 'T' if Award_T_Level == 1 else 'Tx{}'.format(Award_T_Level)
        print('FYI: You qualify for Tx{} but have only applied for {}.'.format(T_Level, T_or_Tx))
    else:
      if T_Level == 1 and self.MyMemberNumber not in SKCC.TribuneLevel:
        print('FYI: You qualify for T but have not yet applied for it.')

    ### S ###

    if self.MyS_Date:
      Award_S_Level = SKCC.SenatorLevel[self.MyMemberNumber]

      if S_Level > Award_S_Level:
        S_or_Sx = 'S' if Award_S_Level == 1 else 'Sx{}'.format(Award_S_Level)
        print('FYI: You qualify for Sx{} but have only applied for {}.'.format(S_Level, S_or_Sx))
    else:
      if S_Level == 1 and self.MyMemberNumber not in SKCC.SenatorLevel:
        print('FYI: You qualify for S but have not yet applied for it.')

    ### WAS and WAS-C ###
    
    if 'WAS' in GOALS:
      if len(self.ContactsForWAS) == len(US_STATES) and MY_CALLSIGN not in SKCC.WasLevel:
        print('FYI: You qualify for WAS but have not yet applied for it.')

    if 'WAS-C' in GOALS:
      if len(self.ContactsForWAS_C) == len(US_STATES) and MY_CALLSIGN not in SKCC.WasCLevel:
        print('FYI: You qualify for WAS-C but have not yet applied for it.')

    if 'P' in GOALS:
      if MY_CALLSIGN in SKCC.PrefixLevel:
        Award_P_Level = SKCC.PrefixLevel[MY_CALLSIGN]

        if P_Level > Award_P_Level:
          print('FYI: You qualify for Px{} but have only applied for Px{}'.format(P_Level, Award_P_Level))
      elif P_Level >= 1:
        print('FYI: You qualify for Px{} but have not yet applied for it.'.format(P_Level))

  @staticmethod
  def CalculateNumerics(Class, Total):
    Increment = Levels[Class]
    SinceLastAchievement = Total % Increment

    Remaining = Increment - SinceLastAchievement

    X_Factor = (Total + Increment) // Increment

    return Remaining, X_Factor

  def ReadQSOs(self):
    Display.Print('Reading QSOs from {}...'.format(ADI_FILE))

    self.QSOs = []

    self.AdiFileReadTimeStamp = os.path.getmtime(ADI_FILE)

    with open(ADI_FILE, 'rb') as File:
      Contents = File.read().decode('utf-8', 'ignore')

    Header, Body = re.split(r'<eoh>', Contents, 0, re.I|re.M)

    Body = Body.strip(' \t\r\n\x1a')  # Include CNTL-Z

    RecordTextList = re.split(r'<eor>', Body, 0, re.I|re.M)

    Adi_RegEx = re.compile(r'<(.*?):.*?(?::.*?)*>(.*?)\s*(?:$|(?=<))', re.I | re.M | re.S)

    for RecordText in RecordTextList:
      RecordText = RecordText.strip()

      if not RecordText:
        continue

      AdiFileMatches = Adi_RegEx.findall(RecordText)

      Record = {}

      for Key, Value in AdiFileMatches:
        Record[Key.upper()] = Value

      if not all(x in Record for x in ('CALL', 'QSO_DATE', 'TIME_ON')):
        print('Warning: ADI record must have CALL, QSO_DATE, and TIME_ON fields. Skipping:')
        print(RecordText)
        continue

      if 'MODE' in Record and Record['MODE'] != 'CW':
        continue

      fFrequency = None

      if 'FREQ' in Record:
        try:
          fFrequency = float(Record['FREQ']) * 1000   # kHz
        except ValueError:
          pass

      QsoCallSign = Record['CALL']
      QsoDate     = Record['QSO_DATE']+Record['TIME_ON']
      QsoSPC      = Record['STATE'] if 'STATE' in Record else None
      QsoFreq     = fFrequency

      self.QSOs.append((QsoDate, QsoCallSign, QsoSPC, QsoFreq))

    self.QSOs = sorted(self.QSOs, key=lambda QsoTuple: QsoTuple[0])

    for QsoDate, CallSign, _SPC, _Freq in self.QSOs:
      CallSign = SKCC.ExtractCallSign(CallSign)

      if not CallSign:
        continue

      MemberNumber = SKCC.Members[CallSign]['plain_number']

      if MemberNumber not in self.QSOsByMemberNumber:
        self.QSOsByMemberNumber[MemberNumber] = [QsoDate]
      else: 
        self.QSOsByMemberNumber[MemberNumber].append(QsoDate)

  def CalcPrefixPoints(self):
    iPoints = 0

    for Prefix in self.ContactsForP:
      QsoDate, Prefix, iMemberNumber, FirstName = self.ContactsForP[Prefix]
      iPoints += iMemberNumber

    return iPoints

  def PrintProgress(self):
    def PrintRemaining(Class, Total):
      Remaining, X_Factor = cQSO.CalculateNumerics(Class, Total)

      if Class in GOALS:
        Abbrev = AbbreviateClass(Class, X_Factor)
        print('Total worked towards {}: {:,}, only need {:,} more for {}.'.format(Class, Total, Remaining, Abbrev))

    print('')

    if GOALS:
      print('GOAL{}: {}'.format(('S' if len(GOALS) > 1 else ''), ', '.join(GOALS)))

    if TARGETS:
      print('TARGET{}: {}'.format(('S' if len(TARGETS) > 1 else ''), ', '.join(TARGETS)))

    print('BANDS: {}'.format(', '.join(str(Band) for Band in BANDS)))

    print('')

    PrintRemaining('C', len(self.ContactsForC))
    PrintRemaining('T', len(self.ContactsForT))
    PrintRemaining('S', len(self.ContactsForS))
    PrintRemaining('P', self.CalcPrefixPoints())

    def RemainingStates(Class, QSOs):
      if len(QSOs) == len(US_STATES):
        Need = 'none needed'
      else:
        RemainingStates = [State for State in US_STATES if State not in QSOs]

        if len(RemainingStates) > 14:
          Need = 'only need {} more'.format(len(RemainingStates))
        else:
          Need = 'only need {}'.format(','.join(RemainingStates))

      print('Total worked towards {}: {}, {}.'.format(Class, len(QSOs), Need))

    if 'WAS' in GOALS:
      RemainingStates('WAS', self.ContactsForWAS)
    
    if 'WAS-C' in GOALS:
      RemainingStates('WAS-C', self.ContactsForWAS_C)

    if 'BRAG' in GOALS:
      NowGMT = cFastDateTime.NowGMT()
      MonthIndex = NowGMT.Month()-1
      MonthName = cFastDateTime.MonthNames[MonthIndex]
      print('Total worked towards {} Brag: {}'.format(MonthName, len(self.Brag)))
    
  def GetGoalHits(self, TheirCallSign, fFrequency = None):
    if TheirCallSign not in SKCC.Members:
      return []

    if TheirCallSign == MY_CALLSIGN:
      return []

    TheirMemberEntry  = SKCC.Members[TheirCallSign]
    TheirC_Date       = Effective(TheirMemberEntry['c_date'])
    TheirT_Date       = Effective(TheirMemberEntry['t_date'])
    TheirMemberNumber = TheirMemberEntry['plain_number']

    List = []

    if 'BRAG' in GOALS:
      if TheirMemberNumber not in self.Brag:
        NowGMT       = cFastDateTime.NowGMT()
        DuringSprint = cSKCC.DuringSprint(NowGMT)

        if fFrequency:
          OnWarcFreq = cSKCC.IsOnWarcFrequency(fFrequency)
          BragOkay   = OnWarcFreq or (not DuringSprint)
        else:
          BragOkay = not DuringSprint

        if BragOkay:
          List.append('BRAG')
      
    if 'C' in GOALS and not self.MyC_Date:
      if TheirMemberNumber not in self.ContactsForC:
        List.append('C')

    if 'CXN' in GOALS and self.MyC_Date:
      if TheirMemberNumber not in self.ContactsForC:
        _, X_Factor = cQSO.CalculateNumerics('C', len(self.ContactsForC))
        List.append(AbbreviateClass('C', X_Factor))

    if 'T' in GOALS and self.MyC_Date and not self.MyT_Date:
      if TheirC_Date and TheirMemberNumber not in self.ContactsForT:
        List.append('T')

    if 'TXN' in GOALS and self.MyT_Date:
      if TheirC_Date and TheirMemberNumber not in self.ContactsForT:
        Remaining, X_Factor = cQSO.CalculateNumerics('T', len(self.ContactsForT))
        List.append(AbbreviateClass('T', X_Factor))

    if 'S' in GOALS and self.MyTX8_Date and not self.MyS_Date:
      if TheirT_Date and TheirMemberNumber not in self.ContactsForS:
        List.append('S')

    if 'SXN' in GOALS and self.MyS_Date:
      if TheirT_Date and TheirMemberNumber not in self.ContactsForS:
        Remaining, X_Factor = cQSO.CalculateNumerics('S', len(self.ContactsForS))
        List.append(AbbreviateClass('S', X_Factor))

    if 'WAS' in GOALS:
      SPC = TheirMemberEntry['spc']
      if SPC in US_STATES and SPC not in self.ContactsForWAS:
        List.append('WAS')

    if 'WAS-C' in GOALS:
      if TheirC_Date:
        SPC = TheirMemberEntry['spc']
        if SPC in US_STATES and SPC not in self.ContactsForWAS_C:
          List.append('WAS-C')

    if 'P' in GOALS:
      Match = cQSO.Prefix_RegEx.match(TheirCallSign)
      Prefix = Match.group(1)
      iTheirMemberNumber   = int(TheirMemberNumber)
      Remaining, X_Factor = cQSO.CalculateNumerics('P', self.CalcPrefixPoints())

      if Prefix in self.ContactsForP:
        iCurrentMemberNumber = self.ContactsForP[Prefix][2]
 
        if iTheirMemberNumber > iCurrentMemberNumber:
          List.append('{}(+{})'.format(AbbreviateClass('P', X_Factor), iTheirMemberNumber - iCurrentMemberNumber))
      else:
        List.append('{}(new +{})'.format(AbbreviateClass('P', X_Factor), iTheirMemberNumber))

    return List

  def GetTargetHits(self, TheirCallSign):
    if TheirCallSign not in SKCC.Members:
      return []

    if TheirCallSign == MY_CALLSIGN:
      return []

    TheirMemberEntry  = SKCC.Members[TheirCallSign]
    TheirJoin_Date    = Effective(TheirMemberEntry['join_date'])
    TheirC_Date       = Effective(TheirMemberEntry['c_date'])
    TheirT_Date       = Effective(TheirMemberEntry['t_date'])
    TheirTX8_Date     = Effective(TheirMemberEntry['tx8_date'])
    TheirS_Date       = Effective(TheirMemberEntry['s_date'])
    TheirMemberNumber = TheirMemberEntry['plain_number']

    List = []

    if 'C' in TARGETS and not TheirC_Date:
      if TheirMemberNumber in self.QSOsByMemberNumber:
        for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
          if QsoDate > TheirJoin_Date and QsoDate > self.MyJoin_Date:
            break
        else:
          List.append('C')
      else:
        List.append('C')

    if 'CXN' in TARGETS and TheirC_Date:
      NextLevel = SKCC.CenturionLevel[TheirMemberNumber]+1

      if NextLevel <= 10:
        if TheirMemberNumber in self.QSOsByMemberNumber:
          for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
            if QsoDate > TheirJoin_Date and QsoDate > self.MyJoin_Date:
              break
          else:
            List.append('Cx{}'.format(NextLevel))
        else:
          List.append('Cx{}'.format(NextLevel))

    if 'T' in TARGETS and TheirC_Date and not TheirT_Date and self.MyC_Date:
      if TheirMemberNumber in self.QSOsByMemberNumber:
        for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
          if QsoDate > TheirC_Date and QsoDate > self.MyC_Date:
            break
        else:
          List.append('T')
      else:
        List.append('T')

    if 'TXN' in TARGETS and TheirT_Date and self.MyC_Date:
      NextLevel = SKCC.TribuneLevel[TheirMemberNumber]+1

      if NextLevel <= 10:
        if TheirMemberNumber in self.QSOsByMemberNumber:
          for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
            if QsoDate > TheirC_Date and QsoDate > self.MyC_Date:
              break
          else:
            List.append('Tx{}'.format(NextLevel))
        else:
          List.append('Tx{}'.format(NextLevel))

    if 'S' in TARGETS and TheirTX8_Date and not TheirS_Date and self.MyT_Date:
      if TheirMemberNumber in self.QSOsByMemberNumber:
        for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
          if QsoDate > TheirTX8_Date and QsoDate > self.MyT_Date:
            break
        else:
          List.append('S')
      else:
        List.append('S')

    if 'SXN' in TARGETS and TheirS_Date and self.MyT_Date:
      NextLevel = SKCC.SenatorLevel[TheirMemberNumber]+1

      if NextLevel <= 10:
        if TheirMemberNumber in self.QSOsByMemberNumber:
          for QsoDate in self.QSOsByMemberNumber[TheirMemberNumber]:
            if QsoDate > TheirTX8_Date and QsoDate > self.MyT_Date:
              break
          else:
            List.append('Sx{}'.format(NextLevel))
        else:
          List.append('Sx{}'.format(NextLevel))

    return List

  def Refresh(self):
    self.ReadQSOs()
    QSOs.GetGoalQSOs()
    self.PrintProgress()

  def GetGoalQSOs(self):
    def Good(QsoDate, MemberDate, MyDate, EligibleDate = None):
      if MemberDate == '' or MyDate == '':
        return False

      if EligibleDate and QsoDate < EligibleDate:
        return False

      return QsoDate >= MemberDate and QsoDate >= MyDate
    
    self.Brag             = {}
    self.ContactsForC     = {}
    self.ContactsForT     = {}
    self.ContactsForS     = {}
    self.ContactsForWAS   = {}
    self.ContactsForWAS_C = {}
    self.ContactsForP     = {}

    TodayGMT = cFastDateTime.NowGMT()
    fastStartOfMonth = TodayGMT.StartOfMonth()
    fastEndOfMonth   = TodayGMT.EndOfMonth()

    for Contact in self.QSOs:
      QsoDate, QsoCallSign, QsoSPC, QsoFreq = Contact

      if QsoCallSign in ('K9SKC', 'K3Y'):
        continue

      QsoCallSign = SKCC.ExtractCallSign(QsoCallSign)

      if not QsoCallSign:
        continue

      MainCallSign = SKCC.Members[QsoCallSign]['main_call']

      TheirMemberEntry  = SKCC.Members[MainCallSign]
      TheirJoin_Date    = Effective(TheirMemberEntry['join_date'])
      TheirC_Date       = Effective(TheirMemberEntry['c_date'])
      TheirT_Date       = Effective(TheirMemberEntry['t_date'])

      TheirMemberNumber = TheirMemberEntry['plain_number']

      fastQsoDate = cFastDateTime(QsoDate)

      # Brag
      if fastStartOfMonth < fastQsoDate < fastEndOfMonth:
        DuringSprint = cSKCC.DuringSprint(fastQsoDate)
        OnWarcFreq   = cSKCC.IsOnWarcFrequency(QsoFreq)

        BragOkay = OnWarcFreq or (not DuringSprint)
  
        #print(BragOkay, DuringSprint, OnWarcFreq, QsoFreq, QsoDate)

        if TheirMemberNumber not in self.Brag and BragOkay:
          self.Brag[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign, QsoFreq)
          #print('Brag contact: {} on {} {}'.format(QsoCallSign, QsoDate, QsoFreq))
        else:
          #print('Not brag eligible: {} on {}  {}'.format(QsoCallSign, QsoDate, QsoFreq))
          pass

      # Prefix
      if Good(QsoDate, TheirJoin_Date, self.MyJoin_Date, '20130101000000'):
        if TheirMemberNumber != self.MyMemberNumber:
          Match  = cQSO.Prefix_RegEx.match(QsoCallSign)
          Prefix = Match.group(1)

          iTheirMemberNumber = int(TheirMemberNumber)

          if Prefix not in self.ContactsForP or iTheirMemberNumber > self.ContactsForP[Prefix][2]:
            FirstName = SKCC.Members[QsoCallSign]['name']
            self.ContactsForP[Prefix] = (QsoDate, Prefix, iTheirMemberNumber, FirstName)

      # Centurion
      if Good(QsoDate, TheirJoin_Date, self.MyJoin_Date):
        if TheirMemberNumber not in self.ContactsForC:
          self.ContactsForC[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

      # Tribune
      if Good(QsoDate, TheirC_Date, self.MyC_Date, '20070301000000'):
        if TheirMemberNumber not in self.ContactsForT:
          self.ContactsForT[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

      # Senator
      if Good(QsoDate, TheirT_Date, self.MyTX8_Date, '20130801000000'):
        if TheirMemberNumber not in self.ContactsForS:
          self.ContactsForS[TheirMemberNumber] = (QsoDate, TheirMemberNumber, MainCallSign)

      if QsoSPC in US_STATES:
        # WAS
        if TheirJoin_Date and QsoDate >= TheirJoin_Date and QsoDate >= self.MyJoin_Date:
          if QsoSPC not in self.ContactsForWAS:
            self.ContactsForWAS[QsoSPC] = (QsoSPC, QsoDate, QsoCallSign)

        # WAS
        if QsoDate >= '20110612000000':
          if TheirC_Date and QsoDate >= TheirC_Date:
            if QsoSPC not in self.ContactsForWAS_C:
              self.ContactsForWAS_C[QsoSPC] = (QsoSPC, QsoDate, QsoCallSign)

    def AwardP(QSOs):
      PrefixList = QSOs.values()
      PrefixList = sorted(PrefixList, key=lambda QsoTuple: QsoTuple[1])

      with open('{}/{}-{}.txt'.format(QSOs_Dir, MY_CALLSIGN, 'P'), 'w') as File:
        iPoints = 0
        for Index, (QsoDate, Prefix, iMemberNumber, FirstName) in enumerate(PrefixList):
          iPoints += iMemberNumber
          File.write('{:>4} {:>8} {:<10.10} {:<6} {:>12,}\n'.format(Index+1, iMemberNumber, FirstName, Prefix, iPoints))

    def AwardCTS(Class, QSOs):
      QSOs = QSOs.values()
      QSOs = sorted(QSOs, key=lambda QsoTuple: (QsoTuple[0], QsoTuple[2]))

      with open('{}/{}-{}.txt'.format(QSOs_Dir, MY_CALLSIGN, Class), 'w') as File:
        for Count, (QsoDate, TheirMemberNumber, MainCallSign) in enumerate(QSOs):
          Date = '{}-{}-{}'.format(QsoDate[0:4], QsoDate[4:6], QsoDate[6:8])
          File.write('{:<4}  {}   {}\n'.format(Count+1, Date, MainCallSign))

    def AwardWAS(Class, QSOs):
      QSOs = QSOs.values()
      QSOs = sorted(QSOs, key=lambda QsoTuple: QsoTuple[0])

      QSOsByState = {QsoSPC: (QsoSPC, QsoDate, QsoCallsign) for QsoSPC, QsoDate, QsoCallsign in QSOs}

      with open('{}/{}-{}.txt'.format(QSOs_Dir, MY_CALLSIGN, Class), 'w') as File:
        for State in US_STATES:
          if State in QSOsByState:
            QsoSPC, QsoDate, QsoCallSign = QSOsByState[State]
            FormattedDate = '{}-{}-{}'.format(QsoDate[0:4], QsoDate[4:6], QsoDate[6:8])
            File.write('{}    {:<12}  {}\n'.format(QsoSPC, QsoCallSign, FormattedDate))
          else:
            File.write('{}\n'.format(State))

    def TrackBRAG(QSOs):
      QSOs = QSOs.values()
      QSOs = sorted(QSOs)

      with open('{}/{}-BRAG.txt'.format(QSOs_Dir, MY_CALLSIGN), 'w') as File:
        for Count, (QsoDate, TheirMemberNumber, MainCallSign, QsoFreq) in enumerate(QSOs):
          Date = '{}-{}-{}'.format(QsoDate[0:4], QsoDate[4:6], QsoDate[6:8])
          File.write('{:<4} {}  {:<6}  {}  {:.3f}\n'.format(Count+1, Date, TheirMemberNumber, MainCallSign, QsoFreq / 1000))
      
    QSOs_Dir = 'QSOs'
    if not os.path.exists(QSOs_Dir):
      os.makedirs(QSOs_Dir)   

    AwardCTS('C',     self.ContactsForC)
    AwardCTS('T',     self.ContactsForT)
    AwardCTS('S',     self.ContactsForS)
    AwardWAS('WAS',   self.ContactsForWAS)
    AwardWAS('WAS-C', self.ContactsForWAS_C)

    AwardP(self.ContactsForP)
    TrackBRAG(self.Brag)

class cSpotters:
  def __init__(self):
    self.Spotters = {}

  @staticmethod
  def locator_to_latlong(locator):
    ''' From pyhamtools '''

    '''
    The MIT License (MIT)

    Copyright (c) 2014 Tobias Wellnitz

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
    '''

    '''converts Maidenhead locator in the corresponding WGS84 coordinates

        Args:
            locator (string): Locator, either 4 or 6 characters

        Returns:
            tuple (float, float): Latitude, Longitude

        Raises:
            ValueError: When called with wrong or invalid input arg
            TypeError: When arg is not a string

        Example:
           The following example converts a Maidenhead locator into Latitude and Longitude

           >>> from pyhamtools.locator import locator_to_latlong
           >>> latitude, longitude = locator_to_latlong("JN48QM")
           >>> print latitude, longitude
           48.5208333333 9.375

        Note:
             Latitude (negative = West, positive = East)
             Longitude (negative = South, positive = North)

    '''

    locator = locator.upper()

    if len(locator) == 5 or len(locator) < 4:
        raise ValueError

    if ord(locator[0]) > ord('R') or ord(locator[0]) < ord('A'):
        raise ValueError

    if ord(locator[1]) > ord('R') or ord(locator[1]) < ord('A'):
        raise ValueError

    if ord(locator[2]) > ord('9') or ord(locator[2]) < ord('0'):
        raise ValueError

    if ord(locator[3]) > ord('9') or ord(locator[3]) < ord('0'):
        raise ValueError

    if len(locator) == 6:
        if ord(locator[4]) > ord('X') or ord(locator[4]) < ord('A'):
            raise ValueError
        if ord(locator[5]) > ord('X') or ord(locator[5]) < ord('A'):
            raise ValueError

    longitude  = (ord(locator[0]) - ord('A')) * 20 - 180
    latitude   = (ord(locator[1]) - ord('A')) * 10 - 90
    longitude += (ord(locator[2]) - ord('0')) * 2
    latitude  += (ord(locator[3]) - ord('0'))

    if len(locator) == 6:
        longitude += ((ord(locator[4])) - ord('A')) * (2 / 24)
        latitude  += ((ord(locator[5])) - ord('A')) * (1 / 24)

        # move to center of subsquare
        longitude += 1 / 24.0
        latitude  += 0.5 / 24.0

    else:
        # move to center of square
        longitude += 1
        latitude  += 0.5

    return latitude, longitude

  @staticmethod
  def calculate_distance(locator1, locator2):
    ''' From pyhamtools '''

    '''
    The MIT License (MIT)

    Copyright (c) 2014 Tobias Wellnitz

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
    '''

    '''calculates the (shortpath) distance between two Maidenhead locators

        Args:
            locator1 (string): Locator, either 4 or 6 characters
            locator2 (string): Locator, either 4 or 6 characters

        Returns:
            float: Distance in km

        Raises:
            ValueError: When called with wrong or invalid input arg
            AttributeError: When args are not a string

        Example:
           The following calculates the distance between two Maidenhead locators in km

           >>> from pyhamtools.locator import calculate_distance
           >>> calculate_distance("JN48QM", "QF67bf")
           16466.413

    '''

    R = 6371 #earh radius
    lat1, long1 = cSpotters.locator_to_latlong(locator1)
    lat2, long2 = cSpotters.locator_to_latlong(locator2)

    d_lat = radians(lat2) - radians(lat1)
    d_long = radians(long2) - radians(long1)

    r_lat1 = radians(lat1)
    r_long1 = radians(long1)
    r_lat2 = radians(lat2)
    r_long2 = radians(long2)

    a = sin(d_lat/2) * sin(d_lat/2) + cos(r_lat1) * cos(r_lat2) * sin(d_long/2) * sin(d_long/2)
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    d = R * c #distance in km

    return d
    
  def GetOnlineSpotters(self):
    def ParseBands(BandString):
      # Each band ends with an 'm'.
     
      BandList = [int(x[:-1]) for x in BandString.split(',') if x.endswith('m')]
      return BandList

    print('')
    print("Finding RBN Spotters within {} miles of '{}'...".format(SPOTTER_RADIUS, MY_GRIDSQUARE))

    SkccGroup_com = cHTTP('reversebeacon.net')
    bHTML         = SkccGroup_com.Get('http://reversebeacon.net/cont_includes/status.php?t=skt').rstrip()
    HTML          = bHTML.decode('utf-8', 'ignore')

    Rows = []
    
    while HTML.find('online24h online7d total">') != -1:
      EndIndex  = HTML.find('</tr>')
      FullIndex = EndIndex+len('</tr>')

      Row = HTML[:FullIndex]
      Rows.append(Row)
      HTML = HTML[FullIndex:]

    Columns_RegEx = re.compile(r'<td.*?><a href="/dxsd1.php\?f=.*?>\s*(.*?)\s*</a>.*?</td>\s*<td.*?>\s*(.*?)</a></td>\s*<td.*?>(.*?)</td>', re.M|re.I|re.S)

    for Row in Rows:
      ColumnMatches = Columns_RegEx.findall(Row)

      for Column in (x for I, x in enumerate(ColumnMatches)):
        Spotter, csvBands, Grid = Column

        if Grid == 'XX88LL':
          continue

        try:
          fKilometers = cSpotters.calculate_distance(MY_GRIDSQUARE, Grid)
        except ValueError:
          #print('Bad GridSquare {} for Spotter {}'.format(Grid, Spotter))
          continue

        fMiles      = fKilometers * 0.62137
        Miles       = int(fMiles)
        BandList    = ParseBands(csvBands)
        self.Spotters[Spotter] = (Miles, BandList)

  def GetNearbySpotters(self):
    List = []

    for Spotter in self.Spotters:
      Miles, Bands = self.Spotters[Spotter]
      List.append((Spotter, Miles, Bands))

    List = sorted(List, key=lambda Tuple: Tuple[1])

    NearbyList = []

    for Spotter, Miles, Bands in List:
      if Miles <= SPOTTER_RADIUS:
        NearbyList.append((Spotter, Miles))

    return NearbyList

  def GetDistance(self, Spotter):
    Miles, Bands = self.Spotters[Spotter]
    return Miles


class cSKCC:
  MonthAbbreviations = {
    'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4,  'May':5,  'Jun':6,
    'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12
  }

  Frequencies = {
    160 : [1820],
    80  : [3530,  3550],
    60  : [],
    40  : [7055,  7120],
    30  : [10120],
    20  : [14050, 14114],
    17  : [18080],
    15  : [21050, 21114],
    12  : [24910],
    10  : [28050, 28114],
    6   : [50090]
  }

  def __init__(self):
    self.Members = {}

    self.ReadSkccData()

    self.CenturionLevel = cSKCC.ReadLevelList('Centurion', 'centurionlist.txt')
    self.TribuneLevel   = cSKCC.ReadLevelList('Tribune',   'tribunelist.txt')
    self.SenatorLevel   = cSKCC.ReadLevelList('Senator',   'senator.txt')

    self.WasLevel       = cSKCC.ReadRoster('WAS',   'operating_awards/was/was_roster.php')
    self.WasCLevel      = cSKCC.ReadRoster('WAS-C', 'operating_awards/was-c/was-c_roster.php')
    self.PrefixLevel    = cSKCC.ReadRoster('PFX',   'operating_awards/pfx/prefix_roster.php')

  @staticmethod
  def WES(Year, Month):
    FromDate      = cFastDateTime((Year, Month, 6))
    StartDate     = FromDate.FirstWeekdayAfterDate('Sat')
    StartDateTime = StartDate + datetime.timedelta(hours=12)
    EndDateTime   = StartDateTime + datetime.timedelta(hours=35, minutes=59, seconds=59)
  
    return StartDateTime, EndDateTime
  
  @staticmethod
  def SKS(Year, Month):
    FromDate = cFastDateTime((Year, Month, 1))
  
    for Count in range(1, 4+1):
      StartDate = FromDate.FirstWeekdayAfterDate('Wed')
      FromDate = StartDate
  
    StartDateTime = StartDate + datetime.timedelta(hours=0)
    EndDateTime   = StartDateTime + datetime.timedelta(hours=2)
  
    return StartDateTime, EndDateTime

  @staticmethod
  def SKSE(Year, Month):
    FromDate      = cFastDateTime((Year, Month, 1))
    StartDate     = FromDate.FirstWeekdayAfterDate('Thu')
    StartDateTime = StartDate + datetime.timedelta(hours=20)
    EndDateTime   = StartDateTime + datetime.timedelta(hours=2)
  
    return StartDateTime, EndDateTime

  @staticmethod
  def DuringSprint(fastDateTime):
    Year  = fastDateTime.Year()
    Month = fastDateTime.Month()
  
    fastWesDateTimeStart, fastWesDateTimeEnd = cSKCC.WES(Year, Month)
  
    if fastWesDateTimeStart <= fastDateTime <= fastWesDateTimeEnd:
      return True

    fastSksDateTimeStart, fastSksDateTimeEnd = cSKCC.SKS(Year, Month)
  
    if fastSksDateTimeStart <= fastDateTime <= fastSksDateTimeEnd:
      return True

    fastSkseDateTimeStart, fastSkseDateTimeEnd = cSKCC.SKSE(Year, Month)
  
    if fastSkseDateTimeStart <= fastDateTime <= fastSkseDateTimeEnd:
      return True
  
    return False

  @staticmethod
  def BlockDuringUpdateWindow():
    UpdateTime = '000000'  # 00:00:00Z

    def TimeNowGMT():
      TimeNowGMT = time.strftime('%H%M00', time.gmtime())
      return int(TimeNowGMT)

    if TimeNowGMT() % 20000 == 0:
      print('The SKCC website updates files every even UTC hour.')
      print('SKCC Skimmer will start when complete.  Please wait...')

      while TimeNowGMT() % 20000 == 0:
        time.sleep(2)
        sys.stderr.write('.')
      else:
        print('')


  ''' The SKCC month abbreviations are always in US format.  We 
      don't want to use the built in date routines because they are
      locale sensitive and could be misinterpreted in other coutries.
  '''
  @staticmethod
  def NormalizeSkccDate(Date):
    if not Date:
      return ''
  
    sDay, sMonthAbbrev, sYear = Date.split()
    iMonth = cSKCC.MonthAbbreviations[sMonthAbbrev]

    return '{:0>4}{:0>2}{:0>2}000000'.format(sYear, iMonth, sDay)

  def ExtractCallSign(self, CallSign):
    if '/' in CallSign:
      if CallSign in self.Members:
        return CallSign

      Parts = CallSign.split('/')

      if len(Parts) == 2:
        Prefix, Suffix = Parts
      elif len(Parts) == 3:
        Prefix, Suffix, _ = Parts
      else:
        return None

      if Prefix in self.Members:
        return Prefix

      if Suffix in self.Members:
        return Suffix
    elif CallSign in self.Members:
      return CallSign
    
    return None

  @staticmethod
  def ReadLevelList(Type, URL):
    print('Retrieving SKCC award info from {}...'.format(URL))

    SkccGroup_com = cHTTP('skccgroup.com')
    bLevelList    = SkccGroup_com.Get('http://www.skccgroup.com/'+URL).rstrip()
    LevelList     = bLevelList.decode('ascii')

    Level = {}
    TodayGMT = time.strftime('%Y%m%d000000', time.gmtime())

    for Line in (x for I, x in enumerate(LevelList.splitlines()) if I > 0):
      CertNumber,CallSign,MemberNumber,FirstName,City,SPC,EffectiveDate,Endorsements = Line.split('|')

      if ' ' in CertNumber:
        CertNumber, X_Factor = CertNumber.split()
        X_Factor = int(X_Factor[1:])
      else:
        X_Factor = 1

      Level[MemberNumber] = X_Factor

      SkccEffectiveDate = cSKCC.NormalizeSkccDate(EffectiveDate)

      if TodayGMT < SkccEffectiveDate:
        print('  FYI: Brand new {}, {}, will be effective 00:00Z {}'.format(Type, CallSign, EffectiveDate))
      elif Type == 'Tribune':
        Match = re.search(r'\*Tx8: (.*?)$', Endorsements)

        if Match:
          Tx8_Date = Match.group(1)
          SkccEffectiveTx8_Date = cSKCC.NormalizeSkccDate(Tx8_Date)

          if TodayGMT < SkccEffectiveTx8_Date:
            print('  FYI: Brand new Tx8, {}, will be effective 00:00Z {}'.format(CallSign, Tx8_Date))

    return Level

  @staticmethod
  def ReadRoster(Name, URL):
    print('Retrieving SKCC {} roster...'.format(Name))

    SkccGroup_com = cHTTP('skccgroup.com')
    bHTML         = SkccGroup_com.Get('http://www.skccgroup.com/'+URL).rstrip()
    HTML          = bHTML.decode('utf-8', 'ignore')

    Rows_RegEx    = re.compile(r'<tr.*?>(.*?)</tr>', re.M|re.I|re.S)
    Columns_RegEx = re.compile(r'<td.*?>(.*?)</td>', re.M|re.I|re.S)

    RowMatches    = Rows_RegEx.findall(HTML)

    Roster = {}

    for Row in (x for I, x in enumerate(RowMatches) if I > 0):
      ColumnMatches = Columns_RegEx.findall(Row)
      CertNumber    = ColumnMatches[0]
      CallSign      = ColumnMatches[1]

      if ' ' in CertNumber:
        CertNumber, X_Factor = CertNumber.split()
        X_Factor = int(X_Factor[1:])
      else:
        X_Factor = 1

      Roster[CallSign] = X_Factor

    return Roster

  
  def ReadSkccData(self):
    print('Retrieving SKCC award dates...')

    SkccGroup_com = cHTTP('skccgroup.com')
    bSkccList     = SkccGroup_com.Get('http://www.skccgroup.com/membership_data/software/skccdata.txt').rstrip()
    SkccList      = bSkccList.decode('ascii')

    Lines = SkccList.splitlines()

    for Line in (x for I, x in enumerate(Lines) if I > 0):
      _Number,CurrentCall,Name,City,SPC,OtherCalls,PlainNumber,_,Join_Date,C_Date,T_Date,TX8_Date,S_Date,Country = Line.split('|')

      if OtherCalls:
        OtherCallList = [x.strip() for x in OtherCalls.split(',')]
      else:
        OtherCallList = []

      AllCalls = [CurrentCall] + OtherCallList

      for Call in AllCalls:
        self.Members[Call] = {
          'name'         : Name,
          'plain_number' : PlainNumber,
          'spc'          : SPC,
          'join_date'    : cSKCC.NormalizeSkccDate(Join_Date),
          'c_date'       : cSKCC.NormalizeSkccDate(C_Date),
          't_date'       : cSKCC.NormalizeSkccDate(T_Date),
          'tx8_date'     : cSKCC.NormalizeSkccDate(TX8_Date),
          's_date'       : cSKCC.NormalizeSkccDate(S_Date),
          'main_call'    : CurrentCall,
        }

  @staticmethod
  def IsOnSkccFrequency(fFrequency, Tolerance = 10):
    for Band in cSKCC.Frequencies:
      if Band == 60 and fFrequency >= 5332-1.5 and fFrequency <= 5405+1.5:
        return True
      
      MidPoints = cSKCC.Frequencies[Band]
  
      for MidPoint in MidPoints:
        if fFrequency >= MidPoint-Tolerance and fFrequency <= MidPoint+Tolerance:
          return True

    return False

  @staticmethod
  def IsOnWarcFrequency(fFrequency, Tolerance = 10):
    WarcBands =  [30, 17, 12]

    for Band in WarcBands:
      MidPoints = cSKCC.Frequencies[Band]
  
      for MidPoint in MidPoints:
        if fFrequency >= MidPoint-Tolerance and fFrequency <= MidPoint+Tolerance:
          return True

    return False

  def GetFullMemberNumber(self, CallSign):
    Entry = self.Members[CallSign]

    MemberNumber = Entry['plain_number']

    Suffix = ''
    Level  = 1

    if Effective(Entry['s_date']):
      Suffix = 'S'
      Level = self.SenatorLevel[MemberNumber]
    elif Effective(Entry['t_date']):
      Suffix = 'T'
      Level = self.TribuneLevel[MemberNumber]

      if Level == 8 and not Effective(Entry['tx8_date']):
        Level = 7
    elif Effective(Entry['c_date']):
      Suffix = 'C'
      Level = self.CenturionLevel[MemberNumber]

    if Level > 1:
      Suffix += 'x{}'.format(Level)

    return (MemberNumber, Suffix)

def Log(Line):
  if LOG_FILE['ENABLED']:
    with open(LOG_FILE['FILE_NAME'], 'a') as File:
      File.write(Line + '\n')

def LogError(Line):
  if LOG_BAD_SPOTS:
    with open('Bad_RBN_Spots.log', 'a') as File:
      File.write(Line + '\n')

def signal_handler(signal, frame):
  sys.exit(16)

def AbbreviateClass(Class, X_Factor):
  if X_Factor > 1:
    return '{}x{}'.format(Class, X_Factor)

  return Class


def BuildMemberInfo(CallSign):
  Entry = SKCC.Members[CallSign]

  Number, Suffix = SKCC.GetFullMemberNumber(CallSign)

  Name = Entry['name']
  SPC  = Entry['spc']

  return '({:>5} {:<4} {:<9.9} {:>3})'.format(Number, Suffix, Name, SPC)

def IsInBANDS(fFrequency):
  def InRange(Band, fFrequency, Low, High):
    return Band in BANDS and fFrequency >= Low and fFrequency <= High

  if InRange(160, fFrequency, 1800, 2000):
    return True

  if InRange(80, fFrequency, 3500, 4000):
    return True

  if InRange(60, fFrequency, 5330.5-1.5, 5403.5+1.5):
    return True

  if InRange(40, fFrequency, 7000, 7300):
    return True

  if InRange(30, fFrequency, 10100, 10150):
    return True

  if InRange(20, fFrequency, 14000, 14350):
    return True

  if InRange(17, fFrequency, 18068, 18168):
    return True

  if InRange(15, fFrequency, 21000, 21450):
    return True

  if InRange(12, fFrequency, 24890, 24990):
    return True

  if InRange(10, fFrequency, 28000, 29700):
    return True

  if InRange(6, fFrequency, 50000, 50100):
    return True

  return False

def Lookups(LookupString):
  def PrintCallSign(CallSign):
    Entry = SKCC.Members[CallSign]

    MyNumber = SKCC.Members[MY_CALLSIGN]['plain_number']

    Report = [BuildMemberInfo(CallSign)]

    if Entry['plain_number'] == MyNumber:
      Report.append('(you)')
    else:
      GoalList = QSOs.GetGoalHits(CallSign)

      if GoalList:
        Report.append('YOU need them for {}'.format(','.join(GoalList)))
  
      TargetList = QSOs.GetTargetHits(CallSign)
  
      if TargetList:
        Report.append('THEY need you for {}'.format(','.join(TargetList)))
  
      if not GoalList and not TargetList:
        Report.append("You don't need to work each other.")

    print('  {} - {}'.format(CallSign, '; '.join(Report)))

  LookupList = SplitCommaSpace(LookupString.upper())

  for Item in LookupList:
    Match = re.match(r'^([0-9]+)[CTS]{0,1}$', Item)

    if Match:
      Number = Match.group(1)

      for CallSign in SKCC.Members:
        Entry = SKCC.Members[CallSign]

        if Entry['plain_number'] == Number:
          if CallSign == Entry['main_call'] == CallSign:
            break
      else:
        print('  No member with the number {}.'.format(Number))
        continue

      PrintCallSign(CallSign)
    else:
      CallSign = SKCC.ExtractCallSign(Item)

      if not CallSign:
        print('  {} - not an SKCC member.'.format(Item))
        continue

      PrintCallSign(CallSign)
  

  print('')


def Usage():
  print('Usage:')
  print('')
  print('   skcc_skimmer.py')
  print('                   [--adi <adi-file>]')
  print('                   [--bands <comma-separated-bands>]')
  print('                   [--callsign <your-callsign>]')
  print('                   [--goals <goals>]')
  print('                   [--help]')
  print('                   [--interactive]')
  print('                   [--logfile <logfile-name>]')
  print('                   [--maidenhead <grid-square>]')
  print('                   [--notification <on|off>]')
  print('                   [--radius <distance-in-miles>]')
  print('                   [--targets <targets>]')
  print('                   [--verbose]')
  print(' or...')
  print('')
  print('   skcc_skimmer.py')
  print('                   [-a <adi-file>]')
  print('                   [-b <comma-separated-bands>]')
  print('                   [-c <your-callsign>]')
  print('                   [-g <goals>]')
  print('                   [-h]')
  print('                   [-i]')
  print('                   [-l <logfile-name>]')
  print('                   [-m <grid-square>]')
  print('                   [-n <on|off>]')
  print('                   [-r <distance-in-miles>]')
  print('                   [-t <targets>]')
  print('                   [-v]')
  print('')
  sys.exit(16)

def FileCheck(Filename):
  if os.path.exists(Filename):
    return

  print('')
  print("File '{}' does not exist.".format(Filename))
  print('')
  sys.exit(16)

#
# Main
# 

VERSION = '3.5.2'

print('SKCC Skimmer Version {}\n'.format(VERSION))

US_STATES = 'AK AL AR AZ CA CO CT DE FL GA ' + \
            'HI IA ID IL IN KS KY LA MA MD ' + \
            'ME MI MN MO MS MT NC ND NE NH ' + \
            'NJ NM NV NY OH OK OR PA RI SC ' + \
            'SD TN TX UT VA VT WA WI WV WY'

#
# Read and execute the contents of 'skcc_skimmer.cfg'.
#

with open('skcc_skimmer.cfg', 'r') as File:
  ConfigFileString = File.read()

exec(ConfigFileString)

if 'QUALIFIERS' in globals():
  print("'QUALIFIERS' is no longer supported and can be removed from 'skcc_skimmer.cfg'.")
  sys.exit(16)

if 'NEARBY' in globals():
  print("'NEARBY' has been replaced with 'SPOTTERS_NEARBY'.")
  sys.exit(16)

if 'SPOTTER_PREFIXES' in globals():
  print("'SPOTTER_PREFIXES' has been deprecated.")
  sys.exit(16)

if 'SPOTTERS_NEARBY' in globals():
  print("'SPOTTERS_NEARBY' has been deprecated.")
  sys.exit(16)

if 'SKCC_FREQUENCIES' in globals():
  print("'SKCC_FREQUENCIES' is now caluclated internally.  Remove it from 'skcc_skimmer.cfg'.")
  sys.exit(16)
  
if 'HITS_FILE' in globals():
  print("'HITS_FILE' is no longer supported.")
  sys.exit(16)

if 'HitCriteria' in globals():
  print("'HitCriteria' is no longer supported.")
  sys.exit(16)

if 'StatusCriteria' in globals():
  print("'StatusCriteria' is no longer supported.")
  sys.exit(16)

if 'SkedCriteria' in globals():
  print("'SkedCriteria' is no longer supported.")
  sys.exit(16)

if 'SkedStatusCriteria' in globals():
  print("'SkedStatusCriteria' is no longer supported.")
  sys.exit(16)

if 'SERVER' in globals():
  print('SERVER is no longer supported.')
  sys.exit(16)

if 'GOAL' in globals():
  print("'GOAL' has been replaced with 'GOALS' and has a different syntax and meaning.")
  sys.exit(16)

if 'GOALS' not in globals():
  print("GOALS must be defined in 'skcc_skimmer.cfg'.")
  sys.exit(16)

if 'TARGETS' not in globals():
  print("TARGETS must be defined in 'skcc_skimmer.cfg'.")
  sys.exit(16)

if 'HIGH_WPM' not in globals():
  print("HIGH_WPM must be defined in 'skcc_skimmer.cfg'.")
  sys.exit(16)

if HIGH_WPM['ACTION'] not in ('suppress', 'warn', 'always-display'):
  print("HIGH_WPM['ACTION'] must be one of ('suppress', 'warn', 'always-display')")
  sys.exit(16)

if 'OFF_FREQUENCY' not in globals():
  print("OFF_FREQUENCY must be defined in 'skcc_skimmer.cfg'.")
  sys.exit(16)

if OFF_FREQUENCY['ACTION'] not in ('suppress', 'warn'):
  print("OFF_FREQUENCY['ACTION'] must be one of ('suppress', 'warn')")
  sys.exit(16)

def Parse(String, ALL, Type):
  ALL  = ALL.split()
  List = SplitCommaSpace(String.upper())

  for x in List:
    if x == 'ALL':
      return ALL

    if x == 'NONE':
      return []

    if x == 'CXN' and 'C' not in List:
      List.append('C')

    if x == 'TXN' and 'T' not in List:
      List.append('T')

    if x == 'SXN' and 'S' not in List:
      List.append('S')

    if x not in ALL:
      print("Unrecognized {} '{}'.".format(Type, x))
      sys.exit(16)

  return List

cSKCC.BlockDuringUpdateWindow()

EXCLUSIONS       = EXCLUSIONS.upper().split()
US_STATES        = US_STATES.upper().split()
FRIENDS          = FRIENDS.upper().split()
MY_CALLSIGN      = MY_CALLSIGN.upper()

Levels = {
 'C'  :    100, 
 'T'  :     50,
 'S'  :    200,
 'P'  : 500000,
}

ArgV = sys.argv[1:]

try:
  Options, Args = getopt.getopt(ArgV, 'ivht:c:a:g:l:m:r:n:b:', \
      'radius notification interactive help maidenhead= callsign= adi= goals= targets= verbose lookup= bands='.split())
except getopt.GetoptError as e:
  print(e)
  Usage()

HaveCallSign = False

if 'VERBOSE' not in globals():
  VERBOSE = False

if 'LOG_BAD_SPOTS' not in globals():
  LOG_BAD_SPOTS = False

INTERACTIVE = False

for Option, Arg in Options:
  if Option in ('-a', '--adi'):
    ADI_FILE = Arg

  elif Option in ('-b', '--bands'):
    BANDS = Arg

  elif Option in ('-c', '--callsign'):
    MY_CALLSIGN = Arg.upper()
    HaveCallSign = True

  elif Option in ('-g', '--goals'):
    GOALS = Arg

  elif Option in ('-h', '--help'):
    Usage()
    sys.exit(16)

  elif Option in ('-i', '--interactive'):
    INTERACTIVE = True

  elif Option in ('-l', '--logfile'):
    LOG_FILE['ENABLED']           = True
    LOG_FILE['DELETE_ON_STARTUP'] = True
    LOG_FILE['FILE_NAME']         = Arg

  elif Option in ('-m', '--maidenhead'):
    MY_GRIDSQUARE = Arg

  elif Option in ('-n', '--notification'):
    Arg = Arg.lower()

    if Arg not in ('on', 'off'):
      print("Notificiation option must be either 'on' or 'off'.")
      sys.exit(16)

    NOTIFICATION['ENABLED'] = Arg == 'on'

  elif Option in ('-r', '--radius'):
    SPOTTER_RADIUS = int(Arg)

  elif Option in ('-t', '--targets'):
    TARGETS = Arg

  elif Option in ('-v', '--verbose'):
    VERBOSE = True

if VERBOSE:
  PROGRESS_DOTS['ENABLED'] = False

#
# MY_CALLSIGN can be defined in skcc_skimmer.cfg.  It is not required
# that it be supplied on the command line.
#
if not MY_CALLSIGN:
  print("You must specify your callsign, either on the command line or in 'skcc_skimmer.cfg'.")
  print('')
  Usage()

if not ADI_FILE:
  print("You must supply an ADI file, either on the command line or in 'skcc_skimmer.cfg'.")
  print('')
  Usage()

GOALS   = Parse(GOALS,   'C CXN T TXN S SXN WAS WAS-C P BRAG', 'goal')
TARGETS = Parse(TARGETS, 'C CXN T TXN S SXN',                  'target')
BANDS   = [int(Band) for Band in SplitCommaSpace(BANDS)]

if not GOALS and not TARGETS:
  print('You must specify at least one goal or target.')
  sys.exit(16)

if 'QUALIFIERS' in globals():
  print("INFO: You no longer need to specify QUALIFIERS.  You may remove it from 'skcc_skimmer.cfg'.")

signal.signal(signal.SIGINT, signal_handler)

FileCheck(ADI_FILE)

Display  = cDisplay()
SKCC     = cSKCC()

if MY_CALLSIGN not in SKCC.Members:
  print("'{}' is not a member of SKCC.".format(MY_CALLSIGN))
  sys.exit(16)

QSOs = cQSO()

QSOs.GetGoalQSOs()
QSOs.PrintProgress()

print('')
QSOs.AwardsCheck()

if INTERACTIVE:
  print('')
  print('Interactive mode. Enter one or more comma or space separated callsigns.') 
  print('')
  print("(Enter 'q' to quit, 'r' to refresh)")
  print('')

  while True:
    sys.stdout.write('> ')
    sys.stdout.flush()
    Line = sys.stdin.readline().strip().lower()
  
    if Line in ('q', 'quit'):
      sys.exit()
    elif Line in ('r', 'refresh'):
      QSOs.Refresh()
    elif Line == '':
      continue
    else:
      print('')
      Lookups(Line)

if 'NOTIFICATION' not in globals():
  print("'NOTIFICATION' must be defined in skcc_skimmer.cfg.")
  sys.exit(16)

BeepCondition = NOTIFICATION['CONDITION'].lower().split(',')

for Condition in BeepCondition:
  if Condition not in ['goals', 'targets']:
    print("NOTIFICATION CONDITION must be 'goals' and/or 'targets'")
    sys.exit(16)


if 'MY_GRIDSQUARE' not in globals():
  print("'MY_GRIDSQUARE' must be defined in skcc_skimmer.cfg.")
  sys.exit(16)

if not MY_GRIDSQUARE:
  print("'MY_GRIDSQUARE' in skcc_skimmer.cfg must be a 4 or 6 character maidenhead grid value.")
  sys.exit(16)

if 'SPOTTER_RADIUS' not in globals():
  print("'SPOTTER_RADIUS' must be defined in skcc_skimmer.cfg.")
  sys.exit(16)

if not isinstance(SPOTTER_RADIUS, (int, )):
  print("'SPOTTER_RADIUS' in skcc_skimmer.cfg must an number - in miles.")
  sys.exit(16)

Spotters = cSpotters()
Spotters.GetOnlineSpotters()

NearbyList = Spotters.GetNearbySpotters()
SpotterList = ['{}({}mi)'.format(Spotter, Miles) for Spotter, Miles in NearbyList]
SPOTTERS_NEARBY = [Spotter for Spotter, Miles in NearbyList]

print('  Found {} spotters:'.format(len(SpotterList)))

List = textwrap.wrap(', '.join(SpotterList), width=80)

for Element in List:
  print('    {}'.format(Element))


if LOG_FILE['DELETE_ON_STARTUP']:
  Filename = LOG_FILE['FILE_NAME']

  if os.path.exists(Filename):
    os.remove(Filename)

print('')
print('Running...')
print('')

SocketLoop = cSocketLoop()

RBN = cRBN_Filter(SocketLoop, CallSign=MY_CALLSIGN, Clusters=CLUSTERS)

if SKED['ENABLED']:
  cSked()

SocketLoop.Run()
